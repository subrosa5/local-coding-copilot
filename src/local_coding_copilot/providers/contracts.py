from collections.abc import Sequence
from typing import Protocol

from local_coding_copilot.models import ChatRequest, ChatResponse, RerankResult


class LLMProvider(Protocol):
    def complete(self, request: ChatRequest) -> ChatResponse: ...


class EmbeddingProvider(Protocol):
    @property
    def fingerprint(self) -> str: ...

    def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


class RerankerProvider(Protocol):
    @property
    def fingerprint(self) -> str: ...

    def rerank(self, query: str, documents: Sequence[str]) -> list[RerankResult]: ...
