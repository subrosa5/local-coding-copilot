from pathlib import Path

import pytest

from local_coding_copilot.providers.model_manifest import build_model_manifest


def test_model_manifest_is_content_derived_and_path_independent(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    (first / "config.json").write_text('{"dim": 3}', encoding="utf-8")
    (second / "config.json").write_text('{"dim": 3}', encoding="utf-8")
    (first / "weights.bin").write_bytes(b"weights")
    (second / "weights.bin").write_bytes(b"weights")

    first_manifest = build_model_manifest(first)
    second_manifest = build_model_manifest(second)

    assert first_manifest["fingerprint"] == second_manifest["fingerprint"]
    (second / "weights.bin").write_bytes(b"changed")
    assert build_model_manifest(second)["fingerprint"] != first_manifest["fingerprint"]


def test_model_manifest_rejects_symlinks(tmp_path: Path) -> None:
    model = tmp_path / "model"
    model.mkdir()
    target = tmp_path / "outside.bin"
    target.write_bytes(b"not part of the model")
    (model / "weights.bin").symlink_to(target)

    with pytest.raises(ValueError, match="symlinks"):
        build_model_manifest(model)
