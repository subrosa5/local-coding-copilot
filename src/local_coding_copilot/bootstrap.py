import os
from dataclasses import dataclass

from local_coding_copilot.auth import PostgresAuthService
from local_coding_copilot.code.indexer import GitCodeIndexer
from local_coding_copilot.code.postgres import PostgresCodeRepository
from local_coding_copilot.providers import (
    EmbeddingProvider,
    FakeEmbeddingProvider,
    FakeLLMProvider,
    LLMProvider,
    RerankerProvider,
    SentenceTransformerEmbeddingProvider,
    SentenceTransformerRerankerProvider,
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
    code_indexer: GitCodeIndexer | None = None


def _configured_embedding_provider() -> EmbeddingProvider:
    model_path = os.environ.get("COPILOT_EMBEDDING_MODEL")
    fingerprint = os.environ.get("COPILOT_EMBEDDING_FINGERPRINT")
    if not model_path and not fingerprint:
        return FakeEmbeddingProvider()
    if not model_path or not fingerprint:
        raise RuntimeError(
            "COPILOT_EMBEDDING_MODEL and COPILOT_EMBEDDING_FINGERPRINT "
            "must be configured together"
        )
    return SentenceTransformerEmbeddingProvider(
        model_path,
        fingerprint=fingerprint,
        device=os.environ.get("COPILOT_MODEL_DEVICE"),
    )


def _configured_reranker_provider() -> RerankerProvider | None:
    model_path = os.environ.get("COPILOT_RERANKER_MODEL")
    fingerprint = os.environ.get("COPILOT_RERANKER_FINGERPRINT")
    if not model_path and not fingerprint:
        return None
    if not model_path or not fingerprint:
        raise RuntimeError(
            "COPILOT_RERANKER_MODEL and COPILOT_RERANKER_FINGERPRINT "
            "must be configured together"
        )
    return SentenceTransformerRerankerProvider(
        model_path,
        fingerprint=fingerprint,
        device=os.environ.get("COPILOT_MODEL_DEVICE"),
    )


def _configured_min_vector_score(embeddings: EmbeddingProvider) -> float:
    configured = os.environ.get("COPILOT_MIN_VECTOR_SCORE")
    if configured is not None:
        try:
            score = float(configured)
        except ValueError as exc:
            raise RuntimeError("COPILOT_MIN_VECTOR_SCORE must be numeric") from exc
        if not 0 <= score <= 1:
            raise RuntimeError("COPILOT_MIN_VECTOR_SCORE must be between 0 and 1")
        return score
    return 0.99 if isinstance(embeddings, FakeEmbeddingProvider) else 0.25


def build_application(
    dsn: str | None = None,
    rate_limiter: RateLimiter | None = None,
    *,
    embeddings: EmbeddingProvider | None = None,
    llm: LLMProvider | None = None,
    reranker: RerankerProvider | None = None,
) -> Application:
    database_dsn_value = dsn or database_dsn()
    repository = PostgresDocumentRepository(database_dsn_value)
    repository.initialize()
    code_repository = PostgresCodeRepository(database_dsn_value)
    code_repository.initialize()
    limiter = rate_limiter or RateLimiter()
    embedding_provider = (
        embeddings if embeddings is not None else _configured_embedding_provider()
    )
    reranker_provider = (
        reranker if reranker is not None else _configured_reranker_provider()
    )
    min_vector_score = _configured_min_vector_score(embedding_provider)
    llm_provider = (
        llm
        if llm is not None
        else FakeLLMProvider(
            response="Fake model received the retrieved context.", cite_sources=True
        )
    )
    code_llm_provider = (
        llm
        if llm is not None
        else FakeLLMProvider(
            response="Fake model received the retrieved code.", cite_sources=True
        )
    )
    return Application(
        service=DocumentRAGService(
            repository=repository,
            embeddings=embedding_provider,
            llm=llm_provider,
            min_vector_score=min_vector_score,
            rate_limiter=limiter,
            reranker=reranker_provider,
        ),
        auth=PostgresAuthService(database_dsn_value),
        code_service=DocumentRAGService(
            repository=code_repository,
            embeddings=embedding_provider,
            llm=code_llm_provider,
            min_vector_score=min_vector_score,
            rate_limiter=limiter,
            reranker=reranker_provider,
        ),
        code_indexer=GitCodeIndexer(code_repository, embedding_provider),
    )


def build_code_indexer(
    dsn: str | None = None, *, embeddings: EmbeddingProvider | None = None
) -> GitCodeIndexer:
    return GitCodeIndexer(
        PostgresCodeRepository(dsn or database_dsn()),
        embeddings if embeddings is not None else _configured_embedding_provider(),
    )


def build_rag_service(dsn: str | None = None) -> DocumentRAGService:
    return build_application(dsn).service
