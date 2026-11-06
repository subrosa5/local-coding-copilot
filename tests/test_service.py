from local_coding_copilot.models import ChatRequest, ChatResponse
from local_coding_copilot.service import CopilotService


class RecordingLLM:
    def __init__(self) -> None:
        self.request: ChatRequest | None = None

    def complete(self, request: ChatRequest) -> ChatResponse:
        self.request = request
        return ChatResponse(content="recorded response")


def test_service_builds_a_chat_request() -> None:
    llm = RecordingLLM()
    service = CopilotService(llm=llm)

    response = service.answer("Explain the matching engine")

    assert response == "recorded response"
    assert llm.request is not None
    assert len(llm.request.messages) == 1
    assert llm.request.messages[0].role == "user"
    assert llm.request.messages[0].content == "Explain the matching engine"
