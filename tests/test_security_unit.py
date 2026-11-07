import pytest
from conftest import InMemoryDocumentRepository

from local_coding_copilot.auth import (
    AuthenticationError,
    AuthorizationError,
    Principal,
)
from local_coding_copilot.providers import FakeEmbeddingProvider, FakeLLMProvider
from local_coding_copilot.rag import Document, DocumentRAGService
from local_coding_copilot.rate_limit import RateLimiter, RateLimitExceeded


def test_query_requires_authentication(rag_service: DocumentRAGService) -> None:
    with pytest.raises(AuthenticationError):
        rag_service.query("order limit")


def test_viewer_cannot_ingest(rag_service: DocumentRAGService) -> None:
    viewer = Principal("viewer", "viewer", frozenset({"default"}))

    with pytest.raises(AuthorizationError, match="admin_role_required"):
        rag_service.ingest_document(
            Document("risk", "risk.md", "v1", "Limit 10"), principal=viewer
        )


def test_cross_project_access_is_denied_before_retrieval(
    rag_service: DocumentRAGService,
) -> None:
    viewer = Principal("viewer", "viewer", frozenset({"project-a"}))

    with pytest.raises(AuthorizationError, match="project_membership_required"):
        rag_service.query("secret", principal=viewer, project_id="project-b")


def test_rate_limit_is_enforced_per_user(admin_principal: Principal) -> None:
    repository = InMemoryDocumentRepository()
    service = DocumentRAGService(
        repository=repository,
        embeddings=FakeEmbeddingProvider(),
        llm=FakeLLMProvider(cite_sources=True),
        rate_limiter=RateLimiter(requests_per_window=1),
    )
    service.ingest_document(
        Document("risk", "risk.md", "v1", "The order limit is 10 USD."),
        principal=admin_principal,
    )

    service.query("order limit", principal=admin_principal)
    with pytest.raises(RateLimitExceeded):
        service.query("order limit", principal=admin_principal)

    assert repository.audit_events[-1]["outcome"] == "denied"
    assert repository.audit_events[-1]["reason"] == "rate_limit_exceeded"
