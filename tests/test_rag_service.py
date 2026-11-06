import pytest

from local_coding_copilot.rag import Document, DocumentRAGService


def test_rag_service_returns_citations_and_retrieval_trace(
    rag_service: DocumentRAGService,
) -> None:
    document = Document(
        document_id="risk",
        source="risk.md",
        version="v1",
        content="The maximum order notional is 1000000 USD.",
    )
    assert rag_service.ingest_document(document) == 1

    response = rag_service.query("maximum order notional")

    assert response.answer == "Grounded fake answer"
    assert response.citations[0].source == "risk.md"
    assert response.citations[0].version == "v1"
    assert response.citations[0].start_line == 1
    assert response.retrieval[0].chunk_id == "risk:0"
    assert response.retrieval[0].lexical_score > 0


def test_rag_service_rejects_blank_questions(
    rag_service: DocumentRAGService,
) -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        rag_service.query("   ")
