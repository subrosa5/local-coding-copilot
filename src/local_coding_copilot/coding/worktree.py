import re
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path, PurePosixPath


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
        base = self.resolve_base_commit(repository, base_commit)
        self._runtime_root.mkdir(parents=True, exist_ok=True)
        path = self._runtime_root / f"task-{uuid.uuid4().hex}"
        _git(repository, "worktree", "add", "--quiet", "--detach", str(path), base)
        return Worktree(path=path, base_commit=base)

    def resolve_base_commit(
        self, repository: Path, base_commit: str | None = None
    ) -> str:
        repository = repository.resolve()
        base = _git(repository, "rev-parse", base_commit or "HEAD")
        _git(repository, "cat-file", "-e", f"{base}^{{commit}}")
        return base

    def apply_patch(self, worktree: Worktree, patch: str) -> None:
        paths = validate_unified_diff(patch)
        for relative_path in paths:
            current = worktree.path
            for part in PurePosixPath(relative_path).parts:
                current = current / part
                if current.is_symlink():
                    raise PatchRejectedError("Patch targets a symlink path")
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

    def remove(self, repository: Path, worktree_path: Path) -> None:
        candidate = worktree_path.resolve()
        if (
            not candidate.is_relative_to(self._runtime_root)
            or re.fullmatch(r"task-[0-9a-f]{32}", candidate.name) is None
        ):
            raise ValueError("Refusing to remove a worktree outside this runtime")
        subprocess.run(
            [
                "git",
                "-C",
                str(repository.resolve()),
                "worktree",
                "remove",
                "--force",
                str(candidate),
            ],
            check=True,
            capture_output=True,
            text=True,
        )


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


def validate_unified_diff(patch: str) -> tuple[str, ...]:
    """Reject malformed or unsafe patches before passing them to git apply."""
    if not patch or not patch.strip():
        raise PatchRejectedError("Patch must not be empty")
    try:
        patch_size = len(patch.encode("utf-8"))
    except UnicodeEncodeError:
        raise PatchRejectedError("Patch contains invalid Unicode") from None
    if patch_size > 1_048_576:
        raise PatchRejectedError("Patch exceeds the 1 MiB limit")
    if (
        not patch.startswith("diff --git ")
        or patch != patch.lstrip()
        or "```" in patch
        or "\x00" in patch
    ):
        raise PatchRejectedError(
            "Patch does not apply: expected only raw unified diff text"
        )
    if any(
        line == "GIT binary patch" or line.startswith("Binary files ")
        for line in patch.splitlines()
    ):
        raise PatchRejectedError("Binary patches are not supported")
    sections: list[list[str]] = []
    for line in patch.splitlines():
        if line.startswith("diff --git "):
            sections.append([line])
        elif sections:
            sections[-1].append(line)
    paths: list[str] = []
    forbidden_headers = (
        "new file mode ",
        "deleted file mode ",
        "old mode ",
        "new mode ",
        "rename from ",
        "rename to ",
        "copy from ",
        "copy to ",
    )
    for section in sections:
        line = section[0]
        match = re.fullmatch(r"diff --git a/(.+) b/(.+)", line)
        if match is None or match.group(1) != match.group(2):
            raise PatchRejectedError("Patch paths must be plain and identical")
        path = match.group(1)
        pure_path = PurePosixPath(path)
        if (
            "\\" in path
            or pure_path.is_absolute()
            or any(part in {"", ".", "..", ".git"} for part in pure_path.parts)
        ):
            raise PatchRejectedError("Patch contains an unsafe repository path")
        hunk_start = next(
            (index for index, header in enumerate(section) if header.startswith("@@")),
            None,
        )
        if hunk_start is None:
            raise PatchRejectedError("Patch is missing unified diff hunks")
        metadata = section[1:hunk_start]
        headers = [line for line in metadata if line.startswith(("--- ", "+++ "))]
        if headers != [f"--- a/{path}", f"+++ b/{path}"]:
            raise PatchRejectedError("Patch file headers do not match diff paths")
        if any(header.startswith(forbidden_headers) for header in metadata):
            raise PatchRejectedError(
                "Patch may not add, delete, rename, or change modes"
            )
        paths.append(path)

    if not paths or len(paths) > 20 or len(paths) != len(set(paths)):
        raise PatchRejectedError(
            "Patch does not apply: expected 1 to 20 unique file diffs"
        )
    return tuple(paths)
