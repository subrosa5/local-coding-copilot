"""Build stable, content-derived manifests for preinstalled model artifacts."""

import hashlib
import json
from pathlib import Path


def build_model_manifest(model_path: Path) -> dict[str, object]:
    root = model_path.resolve(strict=True)
    if not root.is_dir():
        raise ValueError(f"Model path is not a directory: {model_path}")

    files = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"Model directory must not contain symlinks: {path}")
        if not path.is_file():
            continue
        relative_path = path.relative_to(root).as_posix()
        before = path.stat()
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
                digest.update(block)
        after = path.stat()
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise RuntimeError(f"Model artifact changed while hashing: {relative_path}")
        files.append(
            {
                "path": relative_path,
                "size_bytes": after.st_size,
                "sha256": digest.hexdigest(),
            }
        )
    if not files:
        raise ValueError(f"Model directory contains no regular files: {model_path}")

    canonical = json.dumps(files, sort_keys=True, separators=(",", ":")).encode()
    fingerprint = "sha256:" + hashlib.sha256(canonical).hexdigest()
    return {
        "fingerprint": fingerprint,
        "file_count": len(files),
        "total_bytes": sum(file["size_bytes"] for file in files),
        "files": files,
    }
