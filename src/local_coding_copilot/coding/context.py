"""Bounded source context loaders for coding runs and benchmark baselines."""

import re
import subprocess
from pathlib import Path, PurePosixPath

_MAX_SOURCE_FILES = 200
_MAX_FILE_BYTES = 16 * 1024
_MAX_TOTAL_BYTES = 24 * 1024


def load_full_code_context(repository: Path, commit_sha: str) -> tuple[str, ...]:
    """Load a bounded tracked-Python snapshot directly from the requested Git tree."""
    if re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", commit_sha) is None:
        raise ValueError("Base source context requires a resolved full Git commit SHA")
    listing = subprocess.run(
        [
            "git",
            "-C",
            str(repository.resolve()),
            "ls-tree",
            "-r",
            "-rz",
            "--full-tree",
            commit_sha,
        ],
        check=True,
        capture_output=True,
    ).stdout
    entries = [
        entry
        for entry in listing.split(b"\0")
        if entry and entry.rsplit(b"\t", maxsplit=1)[-1].endswith(b".py")
    ]
    if len(entries) > _MAX_SOURCE_FILES:
        raise ValueError("Base source context exceeds the 200-file limit")

    context = []
    total_bytes = 0
    for entry in entries:
        metadata, raw_path = entry.split(b"\t", maxsplit=1)
        mode, object_type, object_sha = metadata.decode("ascii").split()
        if mode not in {"100644", "100755"} or object_type != "blob":
            continue
        try:
            path = raw_path.decode("utf-8")
        except UnicodeDecodeError:
            raise ValueError("Base source context contains a non-UTF-8 path") from None
        _validate_repo_path(path)
        object_size = subprocess.run(
            [
                "git",
                "-C",
                str(repository.resolve()),
                "cat-file",
                "-s",
                object_sha,
            ],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        if int(object_size) > _MAX_FILE_BYTES:
            raise ValueError(f"Base source file exceeds 16 KiB: {path}")
        content = subprocess.run(
            [
                "git",
                "-C",
                str(repository.resolve()),
                "cat-file",
                "blob",
                object_sha,
            ],
            check=True,
            capture_output=True,
        ).stdout
        total_bytes += len(content)
        if total_bytes > _MAX_TOTAL_BYTES:
            raise ValueError("Base source context exceeds the 24 KiB limit")
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError:
            continue
        context.append(f"{path}@{commit_sha}\n{text}")
    if not context:
        raise ValueError("Base commit contains no readable tracked Python files")
    return tuple(context)


def _validate_repo_path(path: str) -> None:
    pure_path = PurePosixPath(path)
    if (
        not path
        or "\\" in path
        or pure_path.is_absolute()
        or any(part in {"", ".", "..", ".git"} for part in pure_path.parts)
    ):
        raise ValueError("Base commit contains an unsafe repository path")
