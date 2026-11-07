import os
import subprocess
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from local_coding_copilot.api import create_app
from local_coding_copilot.auth import AuthorizationError, Principal
from local_coding_copilot.bootstrap import (
    Application,
    build_application,
    build_code_indexer,
)
from local_coding_copilot.code.indexer import GitCodeIndexer
from local_coding_copilot.code.postgres import PostgresCodeRepository


@dataclass(frozen=True)
class CodeContext:
    application: Application
    indexer: GitCodeIndexer
    repository: PostgresCodeRepository
    root: Path
    admin: Principal
    admin_token: str
    viewer: Principal
    project_id: str
    initial_commit: str


def git(root: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *arguments],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def commit(root: Path, message: str) -> str:
    git(root, "add", "-A")
    git(root, "commit", "--quiet", "-m", message)
    return git(root, "rev-parse", "HEAD")


@pytest.fixture
def code_context(tmp_path: Path) -> CodeContext:
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        pytest.skip("DATABASE_URL is not configured")

    git(tmp_path, "init", "--quiet")
    git(tmp_path, "config", "user.email", "tests@example.invalid")
    git(tmp_path, "config", "user.name", "Synthetic Tests")
    (tmp_path / "pricing.py").write_text(
        "def calculate_fee(notional):\n"
        "    return notional * 0.01\n\n"
        "def stable_rule():\n"
        "    return 100\n",
        encoding="utf-8",
    )
    (tmp_path / "obsolete.py").write_text(
        "def obsolete_remote_secret():\n    return 'synthetic'\n", encoding="utf-8"
    )
    initial_commit = commit(tmp_path, "Initial code")

    project_id = f"code-{uuid.uuid4().hex}"
    application = build_application(dsn)
    admin_token = application.auth.create_user(
        f"code-admin-{uuid.uuid4().hex}", "admin", frozenset({project_id})
    )
    viewer_token = application.auth.create_user(
        f"code-viewer-{uuid.uuid4().hex}", "viewer", frozenset({project_id})
    )
    admin = application.auth.authenticate(admin_token)
    viewer = application.auth.authenticate(viewer_token)
    indexer = build_code_indexer(dsn)
    indexer.index(tmp_path, "exchange-test", project_id, principal=admin)
    repository = PostgresCodeRepository(dsn)
    return CodeContext(
        application=application,
        indexer=indexer,
        repository=repository,
        root=tmp_path,
        admin=admin,
        admin_token=admin_token,
        viewer=viewer,
        project_id=project_id,
        initial_commit=initial_commit,
    )


def test_symbol_search_returns_ast_and_commit_metadata(
    code_context: CodeContext,
) -> None:
    response = code_context.application.code_service.query(
        "calculate_fee",
        principal=code_context.viewer,
        project_id=code_context.project_id,
    )

    assert not response.refused
    citation = response.citations[0]
    assert citation.symbol == "calculate_fee"
    assert citation.symbol_kind == "function"
    assert citation.repository == "exchange-test"
    assert citation.source == "pricing.py"
    assert citation.commit_sha == code_context.initial_commit
    assert citation.version == code_context.initial_commit
    assert response.retrieval[0].lexical_score > 0


def test_incremental_postgres_index_updates_and_deletes(
    code_context: CodeContext,
) -> None:
    unchanged = code_context.indexer.index(
        code_context.root,
        "exchange-test",
        code_context.project_id,
        principal=code_context.admin,
    )
    assert unchanged.changed_files == 0
    assert unchanged.deleted_files == 0

    (code_context.root / "pricing.py").write_text(
        "def calculate_fee_v2(notional):\n"
        "    return notional * 0.02\n\n"
        "def stable_rule():\n"
        "    return 100\n",
        encoding="utf-8",
    )
    (code_context.root / "obsolete.py").unlink()
    new_commit = commit(code_context.root, "Update pricing and delete obsolete")
    updated = code_context.indexer.index(
        code_context.root,
        "exchange-test",
        code_context.project_id,
        principal=code_context.admin,
    )

    assert updated.changed_files == 1
    assert updated.deleted_files == 1
    assert (
        code_context.repository.current_commit(code_context.project_id, "exchange-test")
        == new_commit
    )
    changed = code_context.application.code_service.query(
        "calculate_fee_v2",
        principal=code_context.viewer,
        project_id=code_context.project_id,
    )
    stable = code_context.application.code_service.query(
        "stable_rule",
        principal=code_context.viewer,
        project_id=code_context.project_id,
    )
    deleted = code_context.application.code_service.query(
        "obsolete_remote_secret",
        principal=code_context.viewer,
        project_id=code_context.project_id,
    )
    assert changed.citations[0].symbol == "calculate_fee_v2"
    assert changed.citations[0].commit_sha == new_commit
    assert stable.citations[0].commit_sha == new_commit
    assert deleted.refused
    assert not deleted.citations


def test_code_repository_enforces_acl_and_admin_indexing(
    code_context: CodeContext,
) -> None:
    outsider = Principal("outsider", "viewer", frozenset({"other-project"}))

    with pytest.raises(AuthorizationError):
        code_context.application.code_service.query(
            "calculate_fee", principal=outsider, project_id=code_context.project_id
        )
    with pytest.raises(AuthorizationError, match="admin_role_required"):
        code_context.indexer.index(
            code_context.root,
            "exchange-test",
            code_context.project_id,
            principal=code_context.viewer,
        )


def test_http_code_query(code_context: CodeContext) -> None:
    client = TestClient(create_app(code_context.application))

    response = client.post(
        "/v1/code/query",
        json={"question": "calculate_fee", "project_id": code_context.project_id},
        headers={"Authorization": f"Bearer {code_context.admin_token}"},
    )

    assert response.status_code == 200
    citation = response.json()["citations"][0]
    assert citation["symbol"] == "calculate_fee"
    assert citation["commit_sha"] == code_context.initial_commit


@pytest.mark.anyio
async def test_mcp_code_query(code_context: CodeContext) -> None:
    environment = os.environ.copy()
    environment["COPILOT_API_TOKEN"] = code_context.admin_token
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
            "query_code",
            {"question": "calculate_fee", "project_id": code_context.project_id},
        )

    assert not result.is_error
    assert result.structured_content is not None
    citation = result.structured_content["citations"][0]
    assert citation["symbol"] == "calculate_fee"
    assert citation["repository"] == "exchange-test"
