import os

from local_coding_copilot.providers import FakeEmbeddingProvider, FakeLLMProvider
from local_coding_copilot.rag import DocumentRAGService
from local_coding_copilot.rag.postgres import PostgresDocumentRepository


def build_rag_service(dsn: str | None = None) -> DocumentRAGService:
    database_dsn = dsn or os.environ.get("DATABASE_URL")
    if not database_dsn:
        raise RuntimeError("DATABASE_URL is required for the document RAG service")

    repository = PostgresDocumentRepository(database_dsn)
    repository.initialize()
    return DocumentRAGService(
        repository=repository,
        embeddings=FakeEmbeddingProvider(),
        llm=FakeLLMProvider(
            response="Fake model received the retrieved context.", cite_sources=True
        ),
        min_vector_score=0.99,
    )
