from collections.abc import Sequence

import pytest

from local_coding_copilot.providers import FakeEmbeddingProvider, FakeLLMProvider
from local_coding_copilot.rag import DocumentRAGService
from local_coding_copilot.rag.models import Chunk, Document, SearchResult


class InMemoryDocumentRepository:
    def __init__(self) -> None:
        self._chunks: dict[str, Chunk] = {}

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
        self, query: str, embedding: Sequence[float], limit: int
    ) -> list[SearchResult]:
        query_tokens = set(query.casefold().split())
        results = []
        for chunk in self._chunks.values():
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


@pytest.fixture
def rag_service() -> DocumentRAGService:
    return DocumentRAGService(
        repository=InMemoryDocumentRepository(),
        embeddings=FakeEmbeddingProvider(),
        llm=FakeLLMProvider(response="Grounded fake answer", cite_sources=True),
    )
