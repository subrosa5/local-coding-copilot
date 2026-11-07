from collections.abc import Sequence
from typing import Protocol

from local_coding_copilot.rag.models import Chunk, Document, SearchResult


class EmbeddingFingerprintMismatch(RuntimeError):
    """The stored vector index was built with a different embedding model."""


class DocumentRepository(Protocol):
    def initialize(self) -> None: ...

    def replace_document(
        self,
        document: Document,
        chunks: Sequence[Chunk],
        embeddings: Sequence[Sequence[float]],
        embedding_fingerprint: str,
    ) -> None: ...

    def assert_embedding_fingerprint(
        self, project_id: str, embedding_fingerprint: str
    ) -> None: ...

    def delete_documents_except(
        self, project_id: str, document_ids: Sequence[str]
    ) -> int: ...

    def search(
        self,
        query: str,
        embedding: Sequence[float],
        limit: int,
        user_id: str,
        project_id: str,
    ) -> list[SearchResult]: ...

    def record_audit(
        self,
        user_id: str,
        project_id: str,
        action: str,
        transport: str,
        outcome: str,
        reason: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> None: ...
