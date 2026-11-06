import hashlib
from collections.abc import Sequence

from local_coding_copilot.models import ChatRequest, ChatResponse, RerankResult


class FakeLLMProvider:
    def __init__(
        self, response: str = "Fake provider response.", cite_sources: bool = False
    ) -> None:
        self._response = response
        self._cite_sources = cite_sources

    def complete(self, request: ChatRequest) -> ChatResponse:
        if not request.messages:
            raise ValueError("At least one message is required")
        context = next(
            (
                message.content.split("Context:\n", 1)[1]
                for message in request.messages
                if "Context:\n" in message.content
            ),
            "",
        )
        citation_count = sum(line.startswith("[") for line in context.splitlines())
        citations = "".join(f"[{index}]" for index in range(1, citation_count + 1))
        suffix = f" {citations}" if self._cite_sources and citations else ""
        return ChatResponse(content=self._response + suffix)


class FakeEmbeddingProvider:
    def __init__(self, dimension: int = 8) -> None:
        if dimension < 1:
            raise ValueError("Embedding dimension must be positive")
        self._dimension = dimension

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._embed(text) for text in texts]

    def _embed(self, text: str) -> list[float]:
        values = []
        for position in range(self._dimension):
            digest = hashlib.sha256(f"{position}\0{text}".encode()).digest()
            integer = int.from_bytes(digest[:8])
            values.append(integer / ((1 << 64) - 1) * 2 - 1)
        return values


class FakeRerankerProvider:
    def rerank(self, query: str, documents: Sequence[str]) -> list[RerankResult]:
        query_tokens = set(query.casefold().split())
        results = []
        for index, document in enumerate(documents):
            document_tokens = set(document.casefold().split())
            overlap = len(query_tokens & document_tokens)
            score = overlap / len(query_tokens) if query_tokens else 0.0
            results.append(RerankResult(index=index, score=score))
        return sorted(results, key=lambda result: (-result.score, result.index))
