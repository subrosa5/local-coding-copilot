import os
from dataclasses import dataclass

from local_coding_copilot.auth import PostgresAuthService
from local_coding_copilot.code.indexer import GitCodeIndexer
from local_coding_copilot.code.postgres import PostgresCodeRepository
from local_coding_copilot.providers import (
    FakeEmbeddingProvider,
    FakeLLMProvider,
    LLMProvider,
    OpenAICompatibleLLMProvider,
)
from local_coding_copilot.rag import DocumentRAGService
from local_coding_copilot.rag.postgres import PostgresDocumentRepository
from local_coding_copilot.rate_limit import RateLimiter
from local_coding_copilot.settings import database_dsn


@dataclass(frozen=True, slots=True)
class Application:
    service: DocumentRAGService
    auth: PostgresAuthService
    code_service: DocumentRAGService
    llm: LLMProvider


def build_application(
    dsn: str | None = None, rate_limiter: RateLimiter | None = None
) -> Application:
    database_dsn_value = dsn or database_dsn()
    llm = configured_llm_provider()
    repository = PostgresDocumentRepository(database_dsn_value)
    repository.initialize()
    code_repository = PostgresCodeRepository(database_dsn_value)
    code_repository.initialize()
    limiter = rate_limiter or RateLimiter()
    return Application(
        service=DocumentRAGService(
            repository=repository,
            embeddings=FakeEmbeddingProvider(),
            llm=llm,
            min_vector_score=0.99,
            rate_limiter=limiter,
        ),
        auth=PostgresAuthService(database_dsn_value),
        code_service=DocumentRAGService(
            repository=code_repository,
            embeddings=FakeEmbeddingProvider(),
            llm=llm,
            min_vector_score=0.99,
            rate_limiter=limiter,
        ),
        llm=llm,
    )


def configured_llm_provider() -> LLMProvider:
    base_url = os.environ.get("COPILOT_LLM_BASE_URL")
    model = os.environ.get("COPILOT_LLM_MODEL")
    if not base_url and not model:
        return FakeLLMProvider(
            response="Fake model received the retrieved context.", cite_sources=True
        )
    if not base_url or not model:
        raise RuntimeError(
            "COPILOT_LLM_BASE_URL and COPILOT_LLM_MODEL must be configured together"
        )
    try:
        timeout_seconds = float(os.environ.get("COPILOT_LLM_TIMEOUT_SECONDS", "120"))
        max_tokens = int(os.environ.get("COPILOT_LLM_MAX_TOKENS", "8192"))
    except ValueError as exc:
        raise RuntimeError("LLM timeout and max tokens must be numeric") from exc
    return OpenAICompatibleLLMProvider(
        base_url,
        model,
        api_key=os.environ.get("COPILOT_LLM_API_KEY") or None,
        timeout_seconds=timeout_seconds,
        max_tokens=max_tokens,
    )


def build_code_indexer(dsn: str | None = None) -> GitCodeIndexer:
    return GitCodeIndexer(
        PostgresCodeRepository(dsn or database_dsn()), FakeEmbeddingProvider()
    )


def build_rag_service(dsn: str | None = None) -> DocumentRAGService:
    return build_application(dsn).service
