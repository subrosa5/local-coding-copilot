"""Synchronous client for an OpenAI-compatible local inference endpoint."""

import ipaddress
import json
import math
from collections import deque
from contextlib import suppress
from dataclasses import dataclass
from threading import Lock
from time import perf_counter
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import (
    HTTPRedirectHandler,
    ProxyHandler,
    Request,
    build_opener,
)

from local_coding_copilot.models import ChatRequest, ChatResponse, ToolCall


@dataclass(frozen=True, slots=True)
class ProviderStats:
    requests: int
    failures: int
    latency_ms_total: float
    prompt_tokens: int | None
    completion_tokens: int | None
    latency_samples_ms: tuple[float, ...]


class OpenAICompatibleLLMProvider:
    def __init__(
        self,
        base_url: str,
        model: str,
        *,
        api_key: str | None = None,
        timeout_seconds: float = 120.0,
        max_tokens: int = 2048,
    ) -> None:
        self._url = _chat_completions_url(base_url)
        if not isinstance(model, str) or not model.strip():
            raise ValueError("model must not be empty")
        if (
            isinstance(timeout_seconds, bool)
            or not _is_finite_number(timeout_seconds)
            or timeout_seconds <= 0
        ):
            raise ValueError("timeout_seconds must be finite and positive")
        if (
            isinstance(max_tokens, bool)
            or not isinstance(max_tokens, int)
            or max_tokens < 1
        ):
            raise ValueError("max_tokens must be positive")
        if api_key is not None and (
            not isinstance(api_key, str) or "\r" in api_key or "\n" in api_key
        ):
            raise ValueError("api_key must be a string without line breaks")
        self._model = model.strip()
        self._api_key = api_key
        self._timeout_seconds = timeout_seconds
        self._max_tokens = max_tokens
        self._http = build_opener(ProxyHandler({}), _NoRedirectHandler())
        self._stats_lock = Lock()
        self._requests = 0
        self._failures = 0
        self._latency_ms_total = 0.0
        self._prompt_tokens = 0
        self._completion_tokens = 0
        self._usage_seen = False
        self._usage_complete = True
        self._latency_samples_ms: deque[float] = deque(maxlen=4096)

    @property
    def model_name(self) -> str:
        return self._model

    @property
    def endpoint_url(self) -> str:
        return self._url

    @property
    def max_tokens(self) -> int:
        return self._max_tokens

    @property
    def stats(self) -> ProviderStats:
        with self._stats_lock:
            return ProviderStats(
                requests=self._requests,
                failures=self._failures,
                latency_ms_total=self._latency_ms_total,
                prompt_tokens=(
                    self._prompt_tokens
                    if self._usage_seen and self._usage_complete
                    else None
                ),
                completion_tokens=(
                    self._completion_tokens
                    if self._usage_seen and self._usage_complete
                    else None
                ),
                latency_samples_ms=tuple(self._latency_samples_ms),
            )

    def complete(self, request: ChatRequest) -> ChatResponse:
        if not request.messages:
            raise ValueError("At least one message is required")
        if any(message.role == "tool" for message in request.messages):
            _validate_tool_message_flow(request)
        if (
            isinstance(request.temperature, bool)
            or not isinstance(request.temperature, (int, float))
            or not math.isfinite(request.temperature)
            or not 0 <= request.temperature <= 2
        ):
            raise ValueError("temperature must be between 0 and 2")
        if len({tool.name for tool in request.tools}) != len(request.tools):
            raise ValueError("Tool names must be unique")
        if any(
            not tool.name.strip() or not isinstance(tool.parameters, dict)
            for tool in request.tools
        ):
            raise ValueError("Tool names and parameter schemas must be valid")

        payload: dict[str, object] = {
            "model": self._model,
            "messages": [_message_payload(message) for message in request.messages],
            "temperature": request.temperature,
            "max_tokens": self._max_tokens,
            "stream": False,
        }
        if request.tools:
            payload["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.parameters,
                    },
                }
                for tool in request.tools
            ]
            payload["tool_choice"] = "auto"

        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        http_request = Request(
            self._url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        started = perf_counter()
        try:
            with self._http.open(
                http_request, timeout=self._timeout_seconds
            ) as response:
                body = response.read(8 * 1024 * 1024 + 1)
        except HTTPError as exc:
            self._record_call(started, failed=True)
            raise RuntimeError(
                f"Local inference endpoint returned HTTP {exc.code}"
            ) from None
        except (URLError, TimeoutError, OSError) as exc:
            self._record_call(started, failed=True)
            raise RuntimeError(
                f"Could not reach local inference endpoint ({type(exc).__name__})"
            ) from None
        if len(body) > 8 * 1024 * 1024:
            self._record_call(started, failed=True)
            raise RuntimeError("Local inference response exceeded 8 MiB")
        try:
            result = json.loads(
                body,
                object_pairs_hook=_unique_object,
                parse_constant=_reject_json_constant,
            )
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
            self._record_call(started, failed=True)
            raise RuntimeError(
                "Local inference endpoint returned invalid JSON"
            ) from None
        try:
            parsed = _parse_response(result)
            _validate_tool_calls(request, parsed.tool_calls)
        except RuntimeError:
            self._record_call(started, failed=True)
            raise
        usage = result.get("usage") if isinstance(result, dict) else None
        prompt_tokens = usage.get("prompt_tokens") if isinstance(usage, dict) else None
        completion_tokens = (
            usage.get("completion_tokens") if isinstance(usage, dict) else None
        )
        self._record_call(
            started,
            failed=False,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )
        return parsed

    def _record_call(
        self,
        started: float,
        *,
        failed: bool,
        prompt_tokens: object = None,
        completion_tokens: object = None,
    ) -> None:
        with self._stats_lock:
            duration_ms = (perf_counter() - started) * 1000
            self._latency_ms_total += duration_ms
            self._latency_samples_ms.append(duration_ms)
            if failed:
                self._failures += 1
                self._usage_complete = False
                return
            self._requests += 1
            if (
                isinstance(prompt_tokens, int)
                and not isinstance(prompt_tokens, bool)
                and prompt_tokens >= 0
                and isinstance(completion_tokens, int)
                and not isinstance(completion_tokens, bool)
                and completion_tokens >= 0
            ):
                self._usage_seen = True
                self._prompt_tokens += prompt_tokens
                self._completion_tokens += completion_tokens
            else:
                self._usage_complete = False


def _chat_completions_url(base_url: str) -> str:
    parsed = urlsplit(base_url)
    if (
        parsed.scheme != "http"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("base_url must be a plain HTTP loopback URL")
    hostname = parsed.hostname.casefold()
    try:
        port = parsed.port
    except ValueError:
        raise ValueError("base_url has an invalid port") from None
    if port is not None and not 1 <= port <= 65535:
        raise ValueError("base_url has an invalid port")
    try:
        port = parsed.port
    except ValueError:
        raise ValueError("base_url has an invalid port") from None
    if port is not None and not 1 <= port <= 65535:
        raise ValueError("base_url has an invalid port")
    is_loopback = hostname == "localhost"
    with suppress(ValueError):
        is_loopback = is_loopback or ipaddress.ip_address(hostname).is_loopback
    if not is_loopback:
        raise ValueError("inference endpoint must use localhost or a loopback IP")
    path = parsed.path.rstrip("/")
    if path.endswith("/chat/completions"):
        endpoint_path = path
    elif path.endswith("/v1"):
        endpoint_path = f"{path}/chat/completions"
    else:
        endpoint_path = f"{path}/v1/chat/completions"
    return f"http://{parsed.netloc}{endpoint_path}"


class _NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _parse_response(response: object) -> ChatResponse:
    if not isinstance(response, dict):
        raise RuntimeError("Local inference endpoint returned malformed JSON")
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise RuntimeError("Local inference endpoint returned no completion choice")
    if choices[0].get("finish_reason") in {"length", "content_filter"}:
        raise RuntimeError("Local inference completion was truncated or filtered")
    message = choices[0].get("message")
    if not isinstance(message, dict):
        raise RuntimeError("Local inference endpoint returned a malformed message")
    if message.get("role", "assistant") != "assistant":
        raise RuntimeError("Local inference endpoint returned a non-assistant message")
    if message.get("role", "assistant") != "assistant":
        raise RuntimeError("Local inference endpoint returned a non-assistant message")
    content = message.get("content")
    if content is None:
        content = ""
    if not isinstance(content, str):
        raise RuntimeError("Local inference endpoint returned non-text content")
    raw_calls = message.get("tool_calls", [])
    if not isinstance(raw_calls, list):
        raise RuntimeError("Local inference endpoint returned malformed tool calls")
    if len(raw_calls) > 32:
        raise RuntimeError("Local inference endpoint returned too many tool calls")
    calls = tuple(_parse_tool_call(call) for call in raw_calls)
    if not content.strip() and not calls:
        raise RuntimeError("Local inference endpoint returned an empty completion")
    return ChatResponse(content=content, tool_calls=calls)


def _parse_tool_call(value: object) -> ToolCall:
    if not isinstance(value, dict):
        raise RuntimeError("Local inference endpoint returned a malformed tool call")
    function = value.get("function")
    call_id = value.get("id")
    if not isinstance(function, dict):
        raise RuntimeError("Local inference endpoint returned a malformed tool call")
    name = function.get("name")
    raw_arguments = function.get("arguments")
    if (
        not isinstance(call_id, str)
        or not call_id
        or not isinstance(name, str)
        or not name
        or not isinstance(raw_arguments, str)
    ):
        raise RuntimeError("Local inference endpoint returned a malformed tool call")
    try:
        arguments = json.loads(
            raw_arguments,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_json_constant,
        )
    except (json.JSONDecodeError, ValueError):
        raise RuntimeError(
            "Local inference endpoint returned invalid tool JSON"
        ) from None
    if not isinstance(arguments, dict):
        raise RuntimeError("Local inference tool arguments must be a JSON object")
    return ToolCall(name=name, arguments=arguments, call_id=call_id)


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON object key")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"Non-standard JSON constant: {value}")


def _validate_tool_calls(request: ChatRequest, calls: tuple[ToolCall, ...]) -> None:
    if not calls:
        return
    tools = {tool.name: tool for tool in request.tools}
    if not tools:
        raise RuntimeError("Local inference returned tool calls when none were allowed")
    if len({call.call_id for call in calls}) != len(calls):
        raise RuntimeError("Local inference returned duplicate tool call IDs")
    for call in calls:
        tool = tools.get(call.name)
        if tool is None:
            raise RuntimeError("Local inference returned an unrequested tool")
        _validate_schema_value(call.arguments, tool.parameters, "arguments")


def _message_payload(message) -> dict[str, object]:
    if message.role == "tool":
        if not message.tool_call_id or message.tool_calls:
            raise ValueError("Tool messages require a call ID and no nested calls")
        return {
            "role": "tool",
            "tool_call_id": message.tool_call_id,
            "content": message.content,
        }
    if message.tool_call_id is not None:
        raise ValueError("Only tool messages may contain tool_call_id")
    if message.tool_calls and message.role != "assistant":
        raise ValueError("Only assistant messages may contain tool calls")
    payload: dict[str, object] = {"role": message.role, "content": message.content}
    if message.tool_calls:
        if any(not call.call_id for call in message.tool_calls):
            raise ValueError("Assistant tool calls require call IDs")
        payload["tool_calls"] = [
            {
                "id": call.call_id,
                "type": "function",
                "function": {
                    "name": call.name,
                    "arguments": json.dumps(call.arguments, ensure_ascii=False),
                },
            }
            for call in message.tool_calls
        ]
    return payload


def _validate_tool_message_flow(request: ChatRequest) -> None:
    available: set[str] = set()
    consumed: set[str] = set()
    for message in request.messages:
        if message.role == "assistant":
            if message.tool_call_id is not None:
                raise ValueError("Only tool messages may contain tool_call_id")
            for call in message.tool_calls:
                if not call.call_id or call.call_id in available:
                    raise ValueError(
                        "Assistant tool call IDs must be present and unique"
                    )
                available.add(call.call_id)
        elif message.role == "tool":
            if (
                not message.tool_call_id
                or message.tool_call_id not in available
                or message.tool_call_id in consumed
            ):
                raise ValueError("Tool result must match one prior assistant tool call")
            consumed.add(message.tool_call_id)
        elif message.tool_call_id is not None or message.tool_calls:
            raise ValueError("Only assistant/tool messages may contain tool metadata")
    if available != consumed:
        raise ValueError("Every assistant tool call must have one tool result")


def _validate_schema_value(value: object, schema: object, path: str) -> None:
    if not isinstance(schema, dict):
        raise RuntimeError("Configured tool schema must be a JSON Schema object")
    supported_keywords = {
        "type",
        "enum",
        "properties",
        "required",
        "additionalProperties",
        "items",
        "description",
        "title",
    }
    if schema.keys() - supported_keywords:
        raise RuntimeError(
            "Configured tool schema uses unsupported JSON Schema keywords"
        )
    expected = schema.get("type")
    validators = {
        "object": lambda item: isinstance(item, dict),
        "array": lambda item: isinstance(item, list),
        "string": lambda item: isinstance(item, str),
        "integer": lambda item: isinstance(item, int) and not isinstance(item, bool),
        "number": _is_finite_number,
        "boolean": lambda item: isinstance(item, bool),
        "null": lambda item: item is None,
    }
    if expected is not None:
        if not isinstance(expected, str) or expected not in validators:
            raise RuntimeError("Configured tool schema uses an unsupported JSON type")
        if not validators[expected](value):
            raise RuntimeError(f"Tool arguments do not match schema at {path}")
    if "enum" in schema:
        if not isinstance(schema["enum"], list):
            raise RuntimeError("Configured tool schema has an invalid enum")
        if value not in schema["enum"]:
            raise RuntimeError(f"Tool arguments are outside the allowed enum at {path}")

    if isinstance(value, dict):
        properties = schema.get("properties", {})
        required = schema.get("required", [])
        if not isinstance(properties, dict) or not isinstance(required, list):
            raise RuntimeError("Configured tool schema has invalid object constraints")
        if any(not isinstance(name, str) for name in required):
            raise RuntimeError("Configured tool schema has invalid required fields")
        if any(name not in value for name in required):
            raise RuntimeError(f"Tool arguments miss required fields at {path}")
        additional = schema.get("additionalProperties", True)
        if not isinstance(additional, (bool, dict)):
            raise RuntimeError(
                "Configured tool schema has invalid additionalProperties"
            )
        if additional is False and any(name not in properties for name in value):
            raise RuntimeError(f"Tool arguments contain unknown fields at {path}")
        for name, item in value.items():
            if name in properties:
                _validate_schema_value(item, properties[name], f"{path}.{name}")
            elif isinstance(additional, dict):
                _validate_schema_value(item, additional, f"{path}.{name}")
    elif isinstance(value, list) and "items" in schema:
        if not isinstance(schema["items"], dict):
            raise RuntimeError("Configured tool schema has invalid items")
        for index, item in enumerate(value):
            _validate_schema_value(item, schema["items"], f"{path}[{index}]")


def _is_finite_number(value: object) -> bool:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False
