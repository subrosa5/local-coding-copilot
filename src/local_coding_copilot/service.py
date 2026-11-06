from local_coding_copilot.models import ChatRequest, Message
from local_coding_copilot.providers import LLMProvider


class CopilotService:
    def __init__(self, llm: LLMProvider) -> None:
        self._llm = llm

    def answer(self, prompt: str) -> str:
        request = ChatRequest(messages=(Message(role="user", content=prompt),))
        return self._llm.complete(request).content
