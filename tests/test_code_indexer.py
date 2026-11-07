import subprocess
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

import pytest

from local_coding_copilot.auth import AuthorizationError, Principal
from local_coding_copilot.code.indexer import GitCodeIndexer
from local_coding_copilot.code.models import CodeChunk
from local_coding_copilot.providers import FakeEmbeddingProvider


class InMemoryCodeRepository:
    def __init__(self) -> None:
        self.chunks: dict[str, CodeChunk] = {}
        self.commit: str | None = None
        self.audit_events: list[dict[str, object]] = []

    def indexed_files(self, project_id: str, repository: str) -> dict[str, str]:
        return {
            chunk.path: chunk.content_sha256
            for chunk in self.chunks.values()
            if chunk.project_id == project_id and chunk.repository == repository
        }

    def apply_changes(
        self,
        project_id: str,
        repository: str,
        commit_sha: str,
        chunks: Sequence[CodeChunk],
        embeddings: Sequence[Sequence[float]],
        changed_paths: Sequence[str],
        deleted_paths: Sequence[str],
    ) -> None:
        paths = {*changed_paths, *deleted_paths}
        self.chunks = {
            chunk_id: chunk
            for chunk_id, chunk in self.chunks.items()
            if chunk.path not in paths
        }
        self.chunks.update((chunk.chunk_id, chunk) for chunk in chunks)
        self.chunks = {
            chunk_id: replace(chunk, commit_sha=commit_sha)
            for chunk_id, chunk in self.chunks.items()
        }
        self.commit = commit_sha

    def record_audit(self, *args, **kwargs) -> None:
        self.audit_events.append({"args": args, "kwargs": kwargs})


class CountingEmbeddingProvider:
    def __init__(self) -> None:
        self.calls = 0
        self._provider = FakeEmbeddingProvider()

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        self.calls += 1
        return self._provider.embed(texts)


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
def git_repository(tmp_path: Path) -> Path:
    git(tmp_path, "init", "--quiet")
    git(tmp_path, "config", "user.email", "tests@example.invalid")
    git(tmp_path, "config", "user.name", "Synthetic Tests")
    (tmp_path / "pricing.py").write_text(
        "def calculate_fee(notional):\n    return notional * 0.01\n", encoding="utf-8"
    )
    (tmp_path / "obsolete.py").write_text(
        "def obsolete_remote_secret():\n    return 'synthetic'\n", encoding="utf-8"
    )
    commit(tmp_path, "Initial code")
    return tmp_path


def test_incremental_index_updates_changed_and_deleted_files(
    git_repository: Path, admin_principal: Principal
) -> None:
    repository = InMemoryCodeRepository()
    embeddings = CountingEmbeddingProvider()
    indexer = GitCodeIndexer(repository, embeddings)

    initial = indexer.index(
        git_repository, "demo", "default", principal=admin_principal
    )
    unchanged = indexer.index(
        git_repository, "demo", "default", principal=admin_principal
    )

    assert initial.changed_files == 2
    assert unchanged.changed_files == 0
    assert unchanged.deleted_files == 0
    assert embeddings.calls == 1

    (git_repository / "pricing.py").write_text(
        "def calculate_fee_v2(notional):\n    return notional * 0.02\n",
        encoding="utf-8",
    )
    (git_repository / "obsolete.py").unlink()
    new_commit = commit(git_repository, "Update pricing and remove obsolete code")
    updated = indexer.index(
        git_repository, "demo", "default", principal=admin_principal
    )

    assert updated.changed_files == 1
    assert updated.deleted_files == 1
    assert updated.commit_sha == new_commit
    assert repository.commit == new_commit
    assert not any(chunk.path == "obsolete.py" for chunk in repository.chunks.values())
    assert {chunk.symbol for chunk in repository.chunks.values()} == {
        "calculate_fee_v2"
    }


def test_indexer_rejects_dirty_worktree(
    git_repository: Path, admin_principal: Principal
) -> None:
    indexer = GitCodeIndexer(InMemoryCodeRepository(), FakeEmbeddingProvider())
    (git_repository / "pricing.py").write_text("UNCOMMITTED = True\n", encoding="utf-8")

    with pytest.raises(ValueError, match="clean Git worktree"):
        indexer.index(git_repository, "demo", "default", principal=admin_principal)


def test_only_project_admin_can_index(git_repository: Path) -> None:
    repository = InMemoryCodeRepository()
    indexer = GitCodeIndexer(repository, FakeEmbeddingProvider())
    viewer = Principal("viewer", "viewer", frozenset({"default"}))

    with pytest.raises(AuthorizationError, match="admin_role_required"):
        indexer.index(git_repository, "demo", "default", principal=viewer)

    assert repository.audit_events[-1]["args"][4] == "denied"
