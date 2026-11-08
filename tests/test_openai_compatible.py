import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import pytest

from local_coding_copilot.models import ChatRequest, Message, ToolCall, ToolDefinition
from local_coding_copilot.providers.openai_compatible import (
    OpenAICompatibleLLMProvider,
)


class FakeHandler(BaseHTTPRequestHandler):
    status = 200
    response: object = {
        "choices": [{"message": {"content": "local answer", "tool_calls": []}}]
    }
    requests: list[dict[str, object]] = []
    authorization: str | None = None

    def do_POST(self) -> None:
        body = self.rfile.read(int(self.headers["Content-Length"]))
        type(self).requests.append(json.loads(body))
        type(self).authorization = self.headers.get("Authorization")
        payload = json.dumps(type(self).response).encode()
        self.send_response(type(self).status)
        if type(self).status == 302:
            self.send_header("Location", "http://example.com/collect")
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format: str, *args: object) -> None:
        return


@pytest.fixture
def fake_endpoint():
    FakeHandler.status = 200
    FakeHandler.response = {
        "choices": [{"message": {"content": "local answer", "tool_calls": []}}]
    }
    FakeHandler.requests = []
    FakeHandler.authorization = None
    server = ThreadingHTTPServer(("127.0.0.1", 0), FakeHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/v1"
    finally:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()


def test_provider_sends_openai_compatible_chat_request(fake_endpoint: str) -> None:
    FakeHandler.response = {
        "choices": [{"message": {"content": "local answer", "tool_calls": []}}],
        "usage": {"prompt_tokens": 12, "completion_tokens": 3},
    }
    provider = OpenAICompatibleLLMProvider(
        fake_endpoint, "local-coder", api_key="test-secret", max_tokens=321
    )
    response = provider.complete(
        ChatRequest(messages=(Message(role="user", content="hello"),), temperature=0.2)
    )

    assert response.content == "local answer"
    assert response.tool_calls == ()
    assert FakeHandler.authorization == "Bearer test-secret"
    assert FakeHandler.requests == [
        {
            "model": "local-coder",
            "messages": [{"role": "user", "content": "hello"}],
            "temperature": 0.2,
            "max_tokens": 321,
            "stream": False,
        }
    ]
    assert provider.stats.requests == 1
    assert provider.stats.prompt_tokens == 12
    assert provider.stats.completion_tokens == 3
    assert provider.stats.latency_ms_total >= 0


def test_provider_maps_and_parses_function_tool_calls(fake_endpoint: str) -> None:
    FakeHandler.response = {
        "choices": [
            {
                "message": {
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call-1",
                            "type": "function",
                            "function": {
                                "name": "lookup",
                                "arguments": '{"symbol":"fee"}',
                            },
                        }
                    ],
                }
            }
        ]
    }
    provider = OpenAICompatibleLLMProvider(fake_endpoint, "local-coder")
    response = provider.complete(
        ChatRequest(
            messages=(Message(role="user", content="find fee"),),
            tools=(
                ToolDefinition(
                    "lookup", "Search a symbol", {"type": "object", "properties": {}}
                ),
            ),
        )
    )

    assert response.tool_calls[0].name == "lookup"
    assert response.tool_calls[0].arguments == {"symbol": "fee"}
    assert response.tool_calls[0].call_id == "call-1"
    assert FakeHandler.requests[-1]["tools"] == [
        {
            "type": "function",
            "function": {
                "name": "lookup",
                "description": "Search a symbol",
                "parameters": {"type": "object", "properties": {}},
            },
        }
    ]


@pytest.mark.parametrize(
    "url",
    [
        "https://127.0.0.1:8000/v1",
        "http://example.com/v1",
        "http://127.0.0.1:8000/v1?redirect=https://example.com",
        "http://user:password@127.0.0.1:8000/v1",
    ],
)
def test_provider_rejects_non_local_or_ambiguous_endpoint(url: str) -> None:
    with pytest.raises(ValueError):
        OpenAICompatibleLLMProvider(url, "model")


def test_provider_serializes_only_matched_tool_result_messages(
    fake_endpoint: str,
) -> None:
    provider = OpenAICompatibleLLMProvider(fake_endpoint, "local-coder")
    request = ChatRequest(
        messages=(
            Message(
                role="assistant",
                content="",
                tool_calls=(ToolCall("lookup", {"symbol": "fee"}, call_id="call-1"),),
            ),
            Message(role="tool", content="found", tool_call_id="call-1"),
        )
    )
    provider.complete(request)

    assert FakeHandler.requests[-1]["messages"] == [
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "call-1",
                    "type": "function",
                    "function": {
                        "name": "lookup",
                        "arguments": '{"symbol": "fee"}',
                    },
                }
            ],
        },
        {"role": "tool", "tool_call_id": "call-1", "content": "found"},
    ]


def test_provider_rejects_malformed_tool_arguments(fake_endpoint: str) -> None:
    FakeHandler.response = {
        "choices": [
            {
                "message": {
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call-1",
                            "function": {
                                "name": "lookup",
                                "arguments": "not json",
                            },
                        }
                    ],
                }
            }
        ],
        "usage": {},
    }
    provider = OpenAICompatibleLLMProvider(fake_endpoint, "local-coder")
    with pytest.raises(RuntimeError, match="invalid tool JSON"):
        provider.complete(ChatRequest(messages=(Message(role="user", content="x"),)))


@pytest.mark.parametrize("finish_reason", ["length", "content_filter"])
def test_provider_rejects_truncated_or_filtered_completion(
    fake_endpoint: str, finish_reason: str
) -> None:
    FakeHandler.response = {
        "choices": [
            {
                "finish_reason": finish_reason,
                "message": {"content": "partial", "tool_calls": []},
            }
        ]
    }
    provider = OpenAICompatibleLLMProvider(fake_endpoint, "local-coder")
    with pytest.raises(RuntimeError, match="truncated or filtered"):
        provider.complete(ChatRequest(messages=(Message(role="user", content="x"),)))


@pytest.mark.parametrize(
    "request_tools,arguments,match",
    [
        ((), '{"symbol":"fee"}', "when none were allowed"),
        (
            (
                ToolDefinition(
                    "lookup",
                    "Search",
                    {
                        "type": "object",
                        "properties": {"symbol": {"type": "string"}},
                        "required": ["symbol"],
                        "additionalProperties": False,
                    },
                ),
            ),
            "{}",
            "miss required fields",
        ),
        (
            (
                ToolDefinition(
                    "lookup",
                    "Search",
                    {"type": "object", "properties": {"symbol": {"type": "string"}}},
                ),
            ),
            '{"symbol":42}',
            "do not match schema",
        ),
    ],
)
def test_provider_validates_tool_allowlist_and_schema(
    fake_endpoint: str,
    request_tools: tuple[ToolDefinition, ...],
    arguments: str,
    match: str,
) -> None:
    FakeHandler.response = {
        "choices": [
            {
                "message": {
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call-1",
                            "function": {"name": "lookup", "arguments": arguments},
                        }
                    ],
                }
            }
        ]
    }
    provider = OpenAICompatibleLLMProvider(fake_endpoint, "local-coder")
    with pytest.raises(RuntimeError, match=match):
        provider.complete(
            ChatRequest(
                messages=(Message(role="user", content="find fee"),),
                tools=request_tools,
            )
        )


def test_provider_rejects_unmatched_tool_result_message(fake_endpoint: str) -> None:
    provider = OpenAICompatibleLLMProvider(fake_endpoint, "local-coder")
    with pytest.raises(ValueError, match="prior assistant tool call"):
        provider.complete(
            ChatRequest(
                messages=(Message(role="tool", content="result", tool_call_id="x"),)
            )
        )


def test_provider_sanitizes_http_errors(fake_endpoint: str) -> None:
    FakeHandler.status = 500
    FakeHandler.response = {"error": {"message": "private prompt leak"}}
    provider = OpenAICompatibleLLMProvider(fake_endpoint, "local-coder")
    with pytest.raises(RuntimeError, match="HTTP 500") as error:
        provider.complete(ChatRequest(messages=(Message(role="user", content="x"),)))
    assert "private prompt leak" not in str(error.value)


def test_provider_does_not_follow_local_endpoint_redirects(fake_endpoint: str) -> None:
    FakeHandler.status = 302
    provider = OpenAICompatibleLLMProvider(fake_endpoint, "local-coder")
    with pytest.raises(RuntimeError, match="HTTP 302"):
        provider.complete(ChatRequest(messages=(Message(role="user", content="x"),)))
