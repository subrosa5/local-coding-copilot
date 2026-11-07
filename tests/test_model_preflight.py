import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

from local_coding_copilot import model_preflight
from local_coding_copilot.models import RerankResult


class FakeEmbeddingProvider:
    def __init__(self, model_path, *, fingerprint, device):
        self.fingerprint = fingerprint
        self.device = device or "cpu"

    def embed(self, texts):
        return [[0.6, 0.8] for _ in texts]


class FakeRerankerProvider:
    def __init__(self, model_path, *, fingerprint, device):
        self.fingerprint = fingerprint
        self.device = device or "cpu"

    def rerank(self, query, documents):
        return [RerankResult(index=0, score=0.5) for _ in documents]


def test_preflight_hashes_and_smoke_checks_local_artifacts(
    tmp_path: Path, monkeypatch
) -> None:
    embedding_path = tmp_path / "embedding"
    reranker_path = tmp_path / "reranker"
    embedding_path.mkdir()
    reranker_path.mkdir()
    (embedding_path / "model.bin").write_bytes(b"embeddings")
    (reranker_path / "model.bin").write_bytes(b"reranker")
    monkeypatch.setattr(
        model_preflight, "SentenceTransformerEmbeddingProvider", FakeEmbeddingProvider
    )
    monkeypatch.setattr(
        model_preflight, "SentenceTransformerRerankerProvider", FakeRerankerProvider
    )
    monkeypatch.setattr(
        model_preflight.importlib.metadata,
        "version",
        lambda package: "6.2.0",
    )
    torch = ModuleType("torch")
    torch.cuda = SimpleNamespace(is_available=lambda: False)
    torch.backends = SimpleNamespace(mps=SimpleNamespace(is_available=lambda: False))
    monkeypatch.setitem(sys.modules, "torch", torch)

    report = model_preflight.check_models(
        embedding_path, reranker_path=reranker_path, device="cpu"
    )

    assert report["status"] == "ok"
    assert report["embedding"]["dimensions"] == 2
    assert report["embedding"]["normalized"] is True
    assert report["reranker"]["finite_score"] is True
