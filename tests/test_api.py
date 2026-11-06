from fastapi.testclient import TestClient

from local_coding_copilot.api import create_app
from local_coding_copilot.rag import Document, DocumentRAGService


def test_http_query_uses_the_rag_service(rag_service: DocumentRAGService) -> None:
    rag_service.ingest_document(
        Document("risk", "risk.md", "v1", "The order limit is 1000000 USD.")
    )
    client = TestClient(create_app(rag_service))

    response = client.post("/v1/query", json={"question": "order limit"})

    assert response.status_code == 200
    body = response.json()
    assert body["answer"] == "Grounded fake answer"
    assert body["citations"][0]["source"] == "risk.md"
    assert body["retrieval"][0]["chunk_id"] == "risk:0"


def test_http_query_validates_limit(rag_service: DocumentRAGService) -> None:
    client = TestClient(create_app(rag_service))

    response = client.post("/v1/query", json={"question": "test", "limit": 0})

    assert response.status_code == 422
