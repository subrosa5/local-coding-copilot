from collections.abc import Sequence
from typing import Protocol

from local_coding_copilot.rag.models import Chunk, Document, SearchResult


class DocumentRepository(Protocol):
    def initialize(self) -> None: ...

    def replace_document(
        self,
        document: Document,
        chunks: Sequence[Chunk],
        embeddings: Sequence[Sequence[float]],
    ) -> None: ...

    def search(
        self, query: str, embedding: Sequence[float], limit: int
    ) -> list[SearchResult]: ...
