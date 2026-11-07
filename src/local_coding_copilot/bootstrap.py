from dataclasses import dataclass

from local_coding_copilot.auth import PostgresAuthService
from local_coding_copilot.providers import FakeEmbeddingProvider, FakeLLMProvider
from local_coding_copilot.rag import DocumentRAGService
from local_coding_copilot.rag.postgres import PostgresDocumentRepository
from local_coding_copilot.rate_limit import RateLimiter
from local_coding_copilot.settings import database_dsn


@dataclass(frozen=True, slots=True)
class Application:
    service: DocumentRAGService
    auth: PostgresAuthService


def build_application(
    dsn: str | None = None, rate_limiter: RateLimiter | None = None
) -> Application:
    repository = PostgresDocumentRepository(dsn or database_dsn())
    repository.initialize()
    return Application(
        service=DocumentRAGService(
            repository=repository,
            embeddings=FakeEmbeddingProvider(),
            llm=FakeLLMProvider(
                response="Fake model received the retrieved context.", cite_sources=True
            ),
            min_vector_score=0.99,
            rate_limiter=rate_limiter,
        ),
        auth=PostgresAuthService(dsn or database_dsn()),
    )


def build_rag_service(dsn: str | None = None) -> DocumentRAGService:
    return build_application(dsn).service
