import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path


class PatchRejectedError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class Worktree:
    path: Path
    base_commit: str


class GitWorktreeManager:
    def __init__(self, runtime_root: Path) -> None:
        self._runtime_root = runtime_root.resolve()

    def create(self, repository: Path, base_commit: str | None = None) -> Worktree:
        repository = repository.resolve()
        if not repository.is_dir():
            raise ValueError(f"Repository directory does not exist: {repository}")
        if _git(repository, "status", "--porcelain"):
            raise ValueError("Source repository must have a clean Git worktree")
        base = base_commit or _git(repository, "rev-parse", "HEAD")
        _git(repository, "cat-file", "-e", f"{base}^{{commit}}")
        self._runtime_root.mkdir(parents=True, exist_ok=True)
        path = self._runtime_root / f"task-{uuid.uuid4().hex}"
        _git(repository, "worktree", "add", "--quiet", "--detach", str(path), base)
        return Worktree(path=path, base_commit=base)

    def apply_patch(self, worktree: Worktree, patch: str) -> None:
        if not patch.strip():
            raise PatchRejectedError("Patch must not be empty")
        result = _git_with_input(worktree.path, patch, "apply", "--check", "-")
        if result.returncode:
            raise PatchRejectedError("Patch does not apply to the base commit")
        result = _git_with_input(worktree.path, patch, "apply", "-")
        if result.returncode:
            raise PatchRejectedError("Patch application failed")

    def reset(self, worktree: Worktree) -> None:
        _git(worktree.path, "reset", "--hard", "--quiet", worktree.base_commit)
        _git(worktree.path, "clean", "-fdq")

    def diff(self, worktree: Worktree) -> str:
        return _git(worktree.path, "diff", "--no-ext-diff", worktree.base_commit, "--")

    def changed_files(self, worktree: Worktree) -> tuple[str, ...]:
        output = _git(worktree.path, "diff", "--name-only", worktree.base_commit, "--")
        return tuple(output.splitlines())


def _git(root: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *arguments],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _git_with_input(
    root: Path, content: str, *arguments: str
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(root), *arguments],
        input=content,
        capture_output=True,
        text=True,
    )
