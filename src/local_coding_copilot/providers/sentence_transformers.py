"""Optional local embedding and reranking providers.

Models must already exist in the local filesystem/cache. Loading is explicitly
offline so a typo or missing artifact never causes an implicit Hub download.
"""

import re
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from local_coding_copilot.models import RerankResult
from local_coding_copilot.providers.model_manifest import build_model_manifest


class SentenceTransformerEmbeddingProvider:
    def __init__(
        self,
        model_path: str,
        *,
        fingerprint: str,
        device: str | None = None,
        batch_size: int = 32,
        model: Any | None = None,
    ) -> None:
        if not model_path:
            raise ValueError("A local embedding model path is required")
        if batch_size < 1:
            raise ValueError("batch_size must be positive")
        _validate_fingerprint(fingerprint)
        manifest = build_model_manifest(Path(model_path)) if model is None else None
        if manifest is not None and manifest["fingerprint"] != fingerprint:
            raise ValueError(
                "Embedding model files do not match the configured fingerprint"
            )
        self.model_path = model_path
        self.fingerprint = fingerprint
        self.batch_size = batch_size
        self._model = model
        if self._model is None:
            self._model = _load_sentence_transformer(model_path, device)

    @property
    def device(self) -> str:
        return str(getattr(self._model, "device", "unknown"))

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        vectors = self._model.encode(
            list(texts),
            batch_size=self.batch_size,
            show_progress_bar=False,
            convert_to_numpy=True,
            normalize_embeddings=True,
        )
        return [[float(value) for value in vector] for vector in vectors]


class SentenceTransformerRerankerProvider:
    def __init__(
        self,
        model_path: str,
        *,
        fingerprint: str,
        device: str | None = None,
        batch_size: int = 32,
        model: Any | None = None,
    ) -> None:
        if not model_path:
            raise ValueError("A local reranker model path is required")
        if batch_size < 1:
            raise ValueError("batch_size must be positive")
        _validate_fingerprint(fingerprint)
        manifest = build_model_manifest(Path(model_path)) if model is None else None
        if manifest is not None and manifest["fingerprint"] != fingerprint:
            raise ValueError(
                "Reranker model files do not match the configured fingerprint"
            )
        self.model_path = model_path
        self.fingerprint = fingerprint
        self.batch_size = batch_size
        self._model = model
        if self._model is None:
            self._model = _load_cross_encoder(model_path, device)

    @property
    def device(self) -> str:
        return str(getattr(self._model, "device", "unknown"))

    def rerank(self, query: str, documents: Sequence[str]) -> list[RerankResult]:
        if not documents:
            return []
        scores = self._model.predict(
            [(query, document) for document in documents],
            batch_size=self.batch_size,
            show_progress_bar=False,
        )
        results = [
            RerankResult(index=index, score=float(score))
            for index, score in enumerate(scores)
        ]
        return sorted(results, key=lambda result: (-result.score, result.index))


def _load_sentence_transformer(model_path: str, device: str | None) -> Any:
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:
        raise RuntimeError(
            "Install the 'local-models' extra to use local embedding models"
        ) from exc
    return SentenceTransformer(
        model_path,
        device=device,
        local_files_only=True,
        trust_remote_code=False,
    )


def _load_cross_encoder(model_path: str, device: str | None) -> Any:
    try:
        from sentence_transformers import CrossEncoder
    except ImportError as exc:
        raise RuntimeError(
            "Install the 'local-models' extra to use a local reranker"
        ) from exc
    return CrossEncoder(
        model_path,
        device=device,
        local_files_only=True,
        trust_remote_code=False,
    )


def _validate_fingerprint(fingerprint: str) -> None:
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", fingerprint):
        raise ValueError("fingerprint must be a sha256:<64 lowercase hex> value")
