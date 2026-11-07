import pytest

from local_coding_copilot.auth import Principal
from local_coding_copilot.rag import Document, DocumentRAGService


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
