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
        self.audit_events: list[dict[str, object]] = []

    def replace_document(
        self,
        document: Document,
        chunks: Sequence[Chunk],
        embeddings: Sequence[Sequence[float]],
    ) -> None:
        self._chunks = {
            chunk_id: chunk
            for chunk_id, chunk in self._chunks.items()
            if chunk.document_id != document.document_id
        }
        self._chunks.update((chunk.chunk_id, chunk) for chunk in chunks)

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
