import json

from local_coding_copilot.models import ChatRequest, Message
from local_coding_copilot.providers import LLMProvider


class LLMJudge:
    def __init__(self, llm: LLMProvider) -> None:
        self._llm = llm

    def is_supported(self, question: str, answer: str, evidence: str) -> bool:
        request = ChatRequest(
            messages=(
                Message(
                    role="system",
                    content=(
                        'Return only JSON {"supported": true|false}. True only when '
                        "the answer is entailed by the evidence."
                    ),
                ),
                Message(
                    role="user",
                    content=(
                        f"Question: {question}\nAnswer: {answer}\nEvidence: {evidence}"
                    ),
                ),
            )
        )
        response = self._llm.complete(request)
        payload = json.loads(response.content)
        if not isinstance(payload, dict) or type(payload.get("supported")) is not bool:
            raise ValueError("Judge response must contain a boolean supported field")
        return payload["supported"]
