import sys
from types import ModuleType

import pytest

from local_coding_copilot.models import RerankResult
from local_coding_copilot.providers import (
    SentenceTransformerEmbeddingProvider,
    SentenceTransformerRerankerProvider,
)
from local_coding_copilot.providers.model_manifest import build_model_manifest


class EmbeddingModel:
    def encode(self, texts, **kwargs):
        assert kwargs["normalize_embeddings"] is True
        assert kwargs["show_progress_bar"] is False
        return [[0.6, 0.8] for _ in texts]


class CrossEncoderModel:
    def predict(self, pairs, **kwargs):
        assert kwargs["show_progress_bar"] is False
        return [0.2, 0.9][: len(pairs)]


FINGERPRINT = "sha256:" + "0" * 64


def model_directory(root, name):
    path = root / name
    path.mkdir()
    (path / "model.bin").write_bytes(name.encode())
    return path


def test_model_loaders_are_offline_and_disable_remote_code(
    tmp_path, monkeypatch
) -> None:
    calls = []

    class Loader:
        def __init__(self, model_path, **kwargs):
            calls.append((model_path, kwargs))

    module = ModuleType("sentence_transformers")
    module.SentenceTransformer = Loader
    module.CrossEncoder = Loader
    monkeypatch.setitem(sys.modules, "sentence_transformers", module)

    embedding_path = model_directory(tmp_path, "embed")
    reranker_path = model_directory(tmp_path, "rerank")
    embedding_fingerprint = build_model_manifest(embedding_path)["fingerprint"]
    reranker_fingerprint = build_model_manifest(reranker_path)["fingerprint"]
    SentenceTransformerEmbeddingProvider(
        str(embedding_path), fingerprint=embedding_fingerprint
    )
    SentenceTransformerRerankerProvider(
        str(reranker_path), fingerprint=reranker_fingerprint
    )

    assert [path for path, _ in calls] == [str(embedding_path), str(reranker_path)]
    assert all(kwargs["local_files_only"] is True for _, kwargs in calls)
    assert all(kwargs["trust_remote_code"] is False for _, kwargs in calls)


def test_provider_requires_model_path() -> None:
    with pytest.raises(ValueError, match="model path"):
        SentenceTransformerEmbeddingProvider("", fingerprint=FINGERPRINT)


def test_provider_rejects_modified_artifacts(tmp_path) -> None:
    model_path = model_directory(tmp_path, "embed")
    fingerprint = build_model_manifest(model_path)["fingerprint"]
    (model_path / "model.bin").write_bytes(b"changed")

    with pytest.raises(ValueError, match="do not match"):
        SentenceTransformerEmbeddingProvider(str(model_path), fingerprint=fingerprint)


def test_local_embedding_provider_returns_plain_float_vectors() -> None:
    provider = SentenceTransformerEmbeddingProvider(
        "/models/embed", fingerprint=FINGERPRINT, model=EmbeddingModel()
    )

    assert provider.embed(["one", "two"]) == [[0.6, 0.8], [0.6, 0.8]]
    assert provider.embed([]) == []


def test_local_reranker_orders_scores_descending() -> None:
    provider = SentenceTransformerRerankerProvider(
        "/models/rerank", fingerprint=FINGERPRINT, model=CrossEncoderModel()
    )

    assert provider.rerank("question", ["first", "second"]) == [
        RerankResult(index=1, score=0.9),
        RerankResult(index=0, score=0.2),
    ]
