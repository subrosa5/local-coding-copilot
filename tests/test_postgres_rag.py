import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from local_coding_copilot.api import create_app
from local_coding_copilot.auth import Principal
from local_coding_copilot.bootstrap import Application, build_application
from local_coding_copilot.ingestion import load_markdown_documents
from local_coding_copilot.rag.postgres import PostgresDocumentRepository
from local_coding_copilot.rag.repository import EmbeddingFingerprintMismatch


@pytest.fixture(scope="module")
def postgres_application() -> Application:
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        pytest.skip("DATABASE_URL is not configured")
    return build_application(dsn)


@pytest.fixture(scope="module")
def postgres_token(postgres_application: Application) -> str:
    return postgres_application.auth.create_user(
        "rag-admin", "admin", frozenset({"default"})
    )


@pytest.fixture(scope="module")
def postgres_principal(
    postgres_application: Application, postgres_token: str
) -> Principal:
    return postgres_application.auth.authenticate(postgres_token)


@pytest.fixture(scope="module")
def postgres_service(postgres_application: Application, postgres_principal: Principal):
    documents = load_markdown_documents(Path("data/synthetic"))
    for document in documents:
        postgres_application.service.ingest_document(
            document, principal=postgres_principal, transport="test"
        )
    return postgres_application.service


def test_postgres_hybrid_retrieval(postgres_service, postgres_principal) -> None:
    response = postgres_service.query(
        "maximum notional value", limit=3, principal=postgres_principal
    )

    assert response.citations[0].source == "risk-limits.md"
    assert (response.citations[0].start_line, response.citations[0].end_line) == (1, 7)
    assert "maximum notional value" in response.citations[0].text
    assert response.retrieval[0].lexical_score > 0
    assert len(response.citations[0].version) == 64


def test_postgres_document_index_rejects_mixed_embedding_fingerprints(
    postgres_service,
) -> None:
    repository = PostgresDocumentRepository(os.environ["DATABASE_URL"])

    with pytest.raises(EmbeddingFingerprintMismatch, match="different or unknown"):
        repository.assert_embedding_fingerprint("default", "sha256:" + "0" * 64)


def test_http_with_postgres(
    postgres_application: Application, postgres_service, postgres_token: str
) -> None:
    client = TestClient(create_app(postgres_application))

    response = client.post(
        "/v1/query",
        json={"question": "Which component uses price-time priority?", "limit": 3},
        headers={"Authorization": f"Bearer {postgres_token}"},
    )

    assert response.status_code == 200
    body = response.json()
    assert not body["refused"], body
    assert body["citations"][0]["source"] == "matching-engine.md"


@pytest.mark.anyio
async def test_mcp_stdio_with_postgres(
    postgres_application: Application, postgres_service, postgres_token: str
) -> None:
    environment = os.environ.copy()
    environment["COPILOT_API_TOKEN"] = postgres_token
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-m", "local_coding_copilot.mcp_server"],
        env=environment,
    )

    async with (
        stdio_client(parameters) as (read_stream, write_stream),
        ClientSession(read_stream, write_stream) as session,
    ):
        await session.initialize()
        result = await session.call_tool(
            "query_documents",
            {"question": "When is a market data update stale?", "limit": 3},
        )

    assert not result.is_error
    assert result.structured_content is not None
    citations = result.structured_content["citations"]
    assert citations[0]["source"] == "market-data.md"
