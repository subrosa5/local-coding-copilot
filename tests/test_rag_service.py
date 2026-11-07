import pytest

from local_coding_copilot.auth import Principal
from local_coding_copilot.models import RerankResult
from local_coding_copilot.providers import FakeEmbeddingProvider, FakeLLMProvider
from local_coding_copilot.rag import Document, DocumentRAGService
from local_coding_copilot.rag.models import Chunk, SearchResult
from local_coding_copilot.rag.repository import EmbeddingFingerprintMismatch


class RerankRepository:
    def __init__(self):
        self.search_limit = 0

    def search(self, query, embedding, limit, user_id, project_id):
        self.search_limit = limit
        return [
            SearchResult(
                Chunk(
                    f"doc:{index}",
                    "doc",
                    f"{index}.md",
                    "v1",
                    index,
                    1,
                    1,
                    f"Fact {index}",
                ),
                score=1.0 / (index + 1),
                vector_score=0.5,
                lexical_score=0.5,
            )
            for index in range(2)
        ]

    def record_audit(self, *args, **kwargs):
        pass


class ReverseReranker:
    def rerank(self, query, documents):
        return [RerankResult(index=1, score=0.9), RerankResult(index=0, score=0.2)]


def test_reranker_reorders_acl_filtered_candidates(admin_principal: Principal) -> None:
    repository = RerankRepository()
    service = DocumentRAGService(
        repository=repository,
        embeddings=FakeEmbeddingProvider(),
        llm=FakeLLMProvider(response="Supported answer", cite_sources=True),
        min_vector_score=0.1,
        reranker=ReverseReranker(),
    )

    response = service.query("Fact", limit=1, principal=admin_principal)

    assert repository.search_limit == 4
    assert response.citations[0].source == "1.md"
    assert [item.selected for item in response.retrieval] == [True, False]
    assert response.retrieval[0].source == "1.md"
    assert response.retrieval[0].reranker_score == 0.9


def test_rag_service_returns_citations_and_retrieval_trace(
    rag_service: DocumentRAGService, admin_principal: Principal
) -> None:
    document = Document(
        document_id="risk",
        source="risk.md",
        version="v1",
        content="The maximum order notional is 1000000 USD.",
    )
    assert rag_service.ingest_document(document, principal=admin_principal) == 1

    response = rag_service.query("maximum order notional", principal=admin_principal)

    assert response.answer == "Grounded fake answer [1]"
    assert not response.refused
    assert response.citations[0].source == "risk.md"
    assert response.citations[0].version == "v1"
    assert response.citations[0].start_line == 1
    assert response.retrieval[0].chunk_id == "default:risk:0"
    assert response.retrieval[0].lexical_score > 0


def test_rag_service_rejects_blank_questions(
    rag_service: DocumentRAGService, admin_principal: Principal
) -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        rag_service.query("   ", principal=admin_principal)


def test_rag_query_fails_closed_when_embedding_model_differs(
    rag_service: DocumentRAGService, admin_principal: Principal
) -> None:
    rag_service.ingest_document(
        Document("risk", "risk.md", "v1", "order limit is 100"),
        principal=admin_principal,
    )
    changed_model_service = DocumentRAGService(
        repository=rag_service._repository,
        embeddings=FakeEmbeddingProvider(dimension=12),
        llm=FakeLLMProvider(cite_sources=True),
    )

    with pytest.raises(EmbeddingFingerprintMismatch, match="fingerprint mismatch"):
        changed_model_service.query("order limit", principal=admin_principal)


def test_admin_can_prune_documents_missing_from_project_source(
    rag_service: DocumentRAGService, admin_principal: Principal
) -> None:
    rag_service.ingest_document(
        Document("old-policy", "old-policy.md", "v1", "Old policy"),
        principal=admin_principal,
    )

    deleted = rag_service.prune_project_documents(
        set(), principal=admin_principal, project_id="default"
    )
    response = rag_service.query("old policy", principal=admin_principal)

    assert deleted == 1
    assert response.refused
