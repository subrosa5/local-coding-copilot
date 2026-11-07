from fastapi.testclient import TestClient

from local_coding_copilot.api import create_app
from local_coding_copilot.auth import Principal
from local_coding_copilot.bootstrap import Application
from local_coding_copilot.rag import Document


def test_http_query_uses_the_rag_service(
    application: Application, admin_principal: Principal
) -> None:
    application.service.ingest_document(
        Document("risk", "risk.md", "v1", "The order limit is 1000000 USD."),
        principal=admin_principal,
    )
    client = TestClient(create_app(application))

    response = client.post(
        "/v1/query",
        json={"question": "order limit"},
        headers={"Authorization": "Bearer test-token"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["answer"] == "Grounded fake answer [1]"
    assert body["mode"] == "grounded"
    assert not body["refused"]
    assert body["citations"][0]["source"] == "risk.md"
    assert body["retrieval"][0]["chunk_id"] == "default:risk:0"


def test_http_query_requires_valid_bearer_token(application: Application) -> None:
    client = TestClient(create_app(application))

    missing = client.post("/v1/query", json={"question": "test"})
    invalid = client.post(
        "/v1/query",
        json={"question": "test"},
        headers={"Authorization": "Bearer invalid"},
    )

    assert missing.status_code == 401
    assert invalid.status_code == 401


def test_http_query_validates_limit(application: Application) -> None:
    client = TestClient(create_app(application))

    response = client.post(
        "/v1/query",
        json={"question": "test", "limit": 0},
        headers={"Authorization": "Bearer test-token"},
    )

    assert response.status_code == 422
