from collections.abc import Sequence

from local_coding_copilot.auth import Principal
from local_coding_copilot.providers import FakeEmbeddingProvider, FakeLLMProvider
from local_coding_copilot.rag.grounding import validate_grounding
from local_coding_copilot.rag.models import Chunk, Document, SearchResult
from local_coding_copilot.rag.service import DocumentRAGService


def make_result(content: str = "The limit is 1000000 USD.") -> SearchResult:
    return SearchResult(
        chunk=Chunk("risk:0", "risk", "risk.md", "v1", 0, 1, 1, content),
        score=0.1,
        vector_score=0.2,
        lexical_score=0.1,
    )


def test_grounding_accepts_supported_citation_and_number() -> None:
    result = validate_grounding("The limit is 1,000,000 USD [1].", [make_result()])

    assert result.reason is None
    assert result.cited_indexes == (1,)


def test_grounding_rejects_missing_and_invalid_citations() -> None:
    assert validate_grounding("No citation", [make_result()]).reason == (
        "missing_citations"
    )
    assert validate_grounding("Wrong source [2]", [make_result()]).reason == (
        "invalid_citation"
    )


def test_grounding_rejects_unsupported_number() -> None:
    result = validate_grounding("The limit is 42 USD [1].", [make_result()])

    assert result.reason == "unsupported_number"


class IrrelevantRepository:
    def replace_document(
        self,
        document: Document,
        chunks: Sequence[Chunk],
        embeddings: Sequence[Sequence[float]],
    ) -> None:
        pass

    def search(
        self,
        query: str,
        embedding: Sequence[float],
        limit: int,
        user_id: str,
        project_id: str,
    ) -> list[SearchResult]:
        result = make_result("Unrelated evidence")
        return [
            SearchResult(
                result.chunk, result.score, vector_score=0.0, lexical_score=0.0
            )
        ]

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
        pass


def test_service_refuses_without_relevant_evidence(admin_principal: Principal) -> None:
    service = DocumentRAGService(
        repository=IrrelevantRepository(),
        embeddings=FakeEmbeddingProvider(),
        llm=FakeLLMProvider(cite_sources=True),
    )

    response = service.query("Unknown question", principal=admin_principal)

    assert response.refused
    assert response.refusal_reason == "no_relevant_evidence"
    assert response.citations == ()
    assert not response.retrieval[0].selected


class RelevantRepository(IrrelevantRepository):
    def search(
        self,
        query: str,
        embedding: Sequence[float],
        limit: int,
        user_id: str,
        project_id: str,
    ) -> list[SearchResult]:
        return [make_result()]


def test_fast_mode_exposes_uncited_model_answer(admin_principal: Principal) -> None:
    service = DocumentRAGService(
        repository=RelevantRepository(),
        embeddings=FakeEmbeddingProvider(),
        llm=FakeLLMProvider(response="Uncited answer"),
        min_vector_score=0.1,
    )

    response = service.query("Question", mode="fast", principal=admin_principal)

    assert not response.refused
    assert response.answer == "Uncited answer"
    assert response.citations[0].source == "risk.md"
