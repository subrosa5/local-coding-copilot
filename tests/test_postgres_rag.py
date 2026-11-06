import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from local_coding_copilot.api import create_app
from local_coding_copilot.bootstrap import build_rag_service
from local_coding_copilot.ingestion import load_markdown_documents
from local_coding_copilot.rag import DocumentRAGService


@pytest.fixture(scope="module")
def postgres_service() -> DocumentRAGService:
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        pytest.skip("DATABASE_URL is not configured")

    service = build_rag_service(dsn)
    documents = load_markdown_documents(Path("data/synthetic"))
    for document in documents:
        service.ingest_document(document)
    return service


def test_postgres_hybrid_retrieval(postgres_service: DocumentRAGService) -> None:
    response = postgres_service.query("maximum notional value", limit=3)

    assert response.citations[0].source == "risk-limits.md"
    assert (response.citations[0].start_line, response.citations[0].end_line) == (1, 7)
    assert "maximum notional value" in response.citations[0].text
    assert response.retrieval[0].lexical_score > 0
    assert len(response.citations[0].version) == 64


def test_http_with_postgres(postgres_service: DocumentRAGService) -> None:
    client = TestClient(create_app(postgres_service))

    response = client.post(
        "/v1/query",
        json={"question": "Which component uses price-time priority?", "limit": 3},
    )

    assert response.status_code == 200
    body = response.json()
    assert not body["refused"], body
    assert body["citations"][0]["source"] == "matching-engine.md"


@pytest.mark.anyio
async def test_mcp_stdio_with_postgres(postgres_service: DocumentRAGService) -> None:
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-m", "local_coding_copilot.mcp_server"],
        env=os.environ.copy(),
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
