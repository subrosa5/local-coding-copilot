from dataclasses import dataclass

from local_coding_copilot.auth import PostgresAuthService
from local_coding_copilot.code.indexer import GitCodeIndexer
from local_coding_copilot.code.postgres import PostgresCodeRepository
from local_coding_copilot.providers import FakeEmbeddingProvider, FakeLLMProvider
from local_coding_copilot.rag import DocumentRAGService
from local_coding_copilot.rag.postgres import PostgresDocumentRepository
from local_coding_copilot.rate_limit import RateLimiter
from local_coding_copilot.settings import database_dsn


@dataclass(frozen=True, slots=True)
class Application:
    service: DocumentRAGService
    auth: PostgresAuthService
    code_service: DocumentRAGService


def build_application(
    dsn: str | None = None, rate_limiter: RateLimiter | None = None
) -> Application:
    database_dsn_value = dsn or database_dsn()
    repository = PostgresDocumentRepository(database_dsn_value)
    repository.initialize()
    code_repository = PostgresCodeRepository(database_dsn_value)
    code_repository.initialize()
    limiter = rate_limiter or RateLimiter()
    return Application(
        service=DocumentRAGService(
            repository=repository,
            embeddings=FakeEmbeddingProvider(),
            llm=FakeLLMProvider(
                response="Fake model received the retrieved context.", cite_sources=True
            ),
            min_vector_score=0.99,
            rate_limiter=limiter,
        ),
        auth=PostgresAuthService(database_dsn_value),
        code_service=DocumentRAGService(
            repository=code_repository,
            embeddings=FakeEmbeddingProvider(),
            llm=FakeLLMProvider(
                response="Fake model received the retrieved code.", cite_sources=True
            ),
            min_vector_score=0.99,
            rate_limiter=limiter,
        ),
    )


def build_code_indexer(dsn: str | None = None) -> GitCodeIndexer:
    return GitCodeIndexer(
        PostgresCodeRepository(dsn or database_dsn()), FakeEmbeddingProvider()
    )


def build_rag_service(dsn: str | None = None) -> DocumentRAGService:
    return build_application(dsn).service
