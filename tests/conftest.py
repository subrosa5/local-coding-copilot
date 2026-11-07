from collections.abc import Sequence

import pytest

from local_coding_copilot.auth import AuthenticationError, Principal
from local_coding_copilot.bootstrap import Application
from local_coding_copilot.providers import FakeEmbeddingProvider, FakeLLMProvider
from local_coding_copilot.rag import DocumentRAGService
from local_coding_copilot.rag.models import Chunk, Document, SearchResult


class InMemoryDocumentRepository:
    def __init__(self) -> None:
        self._chunks: dict[str, Chunk] = {}
        self._fingerprints: dict[str, str] = {}
        self.audit_events: list[dict[str, object]] = []

    def replace_document(
        self,
        document: Document,
        chunks: Sequence[Chunk],
        embeddings: Sequence[Sequence[float]],
        embedding_fingerprint: str,
    ) -> None:
        self._chunks = {
            chunk_id: chunk
            for chunk_id, chunk in self._chunks.items()
            if chunk.document_id != document.document_id
        }
        self._fingerprints = {
            chunk_id: fingerprint
            for chunk_id, fingerprint in self._fingerprints.items()
            if chunk_id in self._chunks
        }
        self._chunks.update((chunk.chunk_id, chunk) for chunk in chunks)
        self._fingerprints.update(
            (chunk.chunk_id, embedding_fingerprint) for chunk in chunks
        )

    def assert_embedding_fingerprint(self, project_id: str, fingerprint: str) -> None:
        from local_coding_copilot.rag.repository import EmbeddingFingerprintMismatch

        if any(
            chunk.project_id == project_id
            and self._fingerprints.get(chunk_id) != fingerprint
            for chunk_id, chunk in self._chunks.items()
        ):
            raise EmbeddingFingerprintMismatch("Embedding model fingerprint mismatch")

    def delete_documents_except(self, project_id: str, document_ids) -> int:
        keep = set(document_ids)
        removed_documents = {
            chunk.document_id
            for chunk in self._chunks.values()
            if chunk.project_id == project_id and chunk.document_id not in keep
        }
        self._chunks = {
            chunk_id: chunk
            for chunk_id, chunk in self._chunks.items()
            if chunk.document_id not in removed_documents
        }
        self._fingerprints = {
            chunk_id: fingerprint
            for chunk_id, fingerprint in self._fingerprints.items()
            if chunk_id in self._chunks
        }
        return len(removed_documents)

    def search(
        self,
        query: str,
        embedding: Sequence[float],
        limit: int,
        user_id: str,
        project_id: str,
    ) -> list[SearchResult]:
        query_tokens = set(query.casefold().split())
        results = []
        for chunk in self._chunks.values():
            if chunk.project_id != project_id:
                continue
            tokens = set(chunk.content.casefold().split())
            lexical_score = len(query_tokens & tokens)
            results.append(
                SearchResult(
                    chunk=chunk,
                    score=lexical_score,
                    vector_score=0.0,
                    lexical_score=lexical_score,
                )
            )
        return sorted(
            results, key=lambda result: (-result.score, result.chunk.chunk_id)
        )[:limit]

    def record_audit(
        self,
        user_id: str,
        project_id: str,
        action: str,
        transport: str,
        outcome: str,
        reason: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> None:
        self.audit_events.append(
            {
                "user_id": user_id,
                "project_id": project_id,
                "action": action,
                "transport": transport,
                "outcome": outcome,
                "reason": reason,
                "metadata": metadata or {},
            }
        )


class StaticAuthService:
    def __init__(self, principal: Principal, token: str = "test-token") -> None:
        self._principal = principal
        self._token = token

    def authenticate(self, token: str) -> Principal:
        if token != self._token:
            raise AuthenticationError("Invalid API token")
        return self._principal


@pytest.fixture
def admin_principal() -> Principal:
    return Principal("admin", "admin", frozenset({"default"}))


@pytest.fixture
def rag_service() -> DocumentRAGService:
    return DocumentRAGService(
        repository=InMemoryDocumentRepository(),
        embeddings=FakeEmbeddingProvider(),
        llm=FakeLLMProvider(response="Grounded fake answer", cite_sources=True),
    )


@pytest.fixture
def application(
    rag_service: DocumentRAGService, admin_principal: Principal
) -> Application:
    return Application(
        rag_service, StaticAuthService(admin_principal), code_service=rag_service
    )
