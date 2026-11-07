import hashlib
import subprocess
from pathlib import Path

from local_coding_copilot.auth import (
    AuthenticationError,
    AuthorizationError,
    Principal,
)
from local_coding_copilot.code.models import CodeIndexResult
from local_coding_copilot.code.parser import parse_python_file
from local_coding_copilot.code.postgres import PostgresCodeRepository
from local_coding_copilot.providers import EmbeddingProvider


class GitCodeIndexer:
    def __init__(
        self,
        repository: PostgresCodeRepository,
        embeddings: EmbeddingProvider,
    ) -> None:
        self._repository = repository
        self._embeddings = embeddings

    def index(
        self,
        root: Path,
        repository: str,
        project_id: str,
        *,
        principal: Principal | None,
        transport: str = "internal",
    ) -> CodeIndexResult:
        self._authorize(principal, project_id, transport)
        root = root.resolve()
        if not root.is_dir():
            raise ValueError(f"Repository directory does not exist: {root}")
        if _git(root, "status", "--porcelain"):
            raise ValueError("Repository must have a clean Git worktree")

        commit_sha = _git(root, "rev-parse", "HEAD")
        tracked_paths = sorted(_git(root, "ls-files", "--", "*.py").splitlines())
        current_hashes = {}
        contents = {}
        for path in tracked_paths:
            content = (root / path).read_text(encoding="utf-8")
            contents[path] = content
            current_hashes[path] = hashlib.sha256(content.encode()).hexdigest()

        previous_hashes = self._repository.indexed_files(project_id, repository)
        changed_paths = tuple(
            path
            for path in tracked_paths
            if previous_hashes.get(path) != current_hashes[path]
        )
        deleted_paths = tuple(sorted(previous_hashes.keys() - current_hashes.keys()))
        chunks = [
            chunk
            for path in changed_paths
            for chunk in parse_python_file(
                project_id,
                repository,
                path,
                contents[path],
                current_hashes[path],
                commit_sha,
            )
        ]
        embeddings = (
            self._embeddings.embed([chunk.content for chunk in chunks])
            if chunks
            else []
        )
        self._repository.apply_changes(
            project_id,
            repository,
            commit_sha,
            chunks,
            embeddings,
            changed_paths,
            deleted_paths,
        )
        result = CodeIndexResult(
            commit_sha=commit_sha,
            indexed_files=len(tracked_paths),
            changed_files=len(changed_paths),
            deleted_files=len(deleted_paths),
            indexed_chunks=len(chunks),
        )
        self._repository.record_audit(
            principal.user_id,
            project_id,
            "code_index",
            transport,
            "success",
            metadata={
                "repository": repository,
                "commit_sha": commit_sha,
                "changed_files": result.changed_files,
                "deleted_files": result.deleted_files,
                "indexed_chunks": result.indexed_chunks,
            },
        )
        return result

    def _authorize(
        self, principal: Principal | None, project_id: str, transport: str
    ) -> None:
        if principal is None:
            raise AuthenticationError("An authenticated principal is required")
        reason = None
        if project_id not in principal.project_ids:
            reason = "project_membership_required"
        elif principal.role != "admin":
            reason = "admin_role_required"
        if reason:
            self._repository.record_audit(
                principal.user_id,
                project_id,
                "code_index",
                transport,
                "denied",
                reason,
            )
            raise AuthorizationError(reason)


def _git(root: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *arguments],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
