import pytest

from local_coding_copilot import bootstrap
from local_coding_copilot.providers import FakeEmbeddingProvider


def test_configured_local_embedding_requires_path_and_fingerprint(monkeypatch) -> None:
    monkeypatch.setenv("COPILOT_EMBEDDING_MODEL", "/models/embed")
    monkeypatch.delenv("COPILOT_EMBEDDING_FINGERPRINT", raising=False)

    with pytest.raises(RuntimeError, match="must be configured together"):
        bootstrap._configured_embedding_provider()


def test_fake_and_local_vector_threshold_defaults(monkeypatch) -> None:
    monkeypatch.delenv("COPILOT_MIN_VECTOR_SCORE", raising=False)

    assert bootstrap._configured_min_vector_score(FakeEmbeddingProvider()) == 0.99

    class LocalProvider:
        fingerprint = "sha256:" + "1" * 64

    assert bootstrap._configured_min_vector_score(LocalProvider()) == 0.25


def test_vector_threshold_override_is_validated(monkeypatch) -> None:
    monkeypatch.setenv("COPILOT_MIN_VECTOR_SCORE", "0.42")

    assert bootstrap._configured_min_vector_score(FakeEmbeddingProvider()) == 0.42

    monkeypatch.setenv("COPILOT_MIN_VECTOR_SCORE", "1.1")
    with pytest.raises(RuntimeError, match="between 0 and 1"):
        bootstrap._configured_min_vector_score(FakeEmbeddingProvider())
