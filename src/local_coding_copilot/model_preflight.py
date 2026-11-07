"""Offline validation for local embedding and reranker model artifacts."""

import argparse
import importlib.metadata
import json
import math
import platform
from pathlib import Path

from local_coding_copilot.providers import (
    SentenceTransformerEmbeddingProvider,
    SentenceTransformerRerankerProvider,
)
from local_coding_copilot.providers.model_manifest import build_model_manifest


def check_models(
    embedding_path: Path,
    *,
    reranker_path: Path | None = None,
    device: str | None = None,
) -> dict[str, object]:
    embedding_manifest = build_model_manifest(embedding_path)
    embeddings = SentenceTransformerEmbeddingProvider(
        str(embedding_path),
        fingerprint=str(embedding_manifest["fingerprint"]),
        device=device,
    )
    vectors = embeddings.embed(["exchange account risk", "market order matching"])
    if len(vectors) != 2 or not vectors[0] or len(vectors[0]) != len(vectors[1]):
        raise RuntimeError("Embedding model returned an invalid vector shape")
    if any(not math.isfinite(value) for vector in vectors for value in vector):
        raise RuntimeError("Embedding model returned a non-finite vector value")
    norms = [math.sqrt(sum(value * value for value in vector)) for vector in vectors]
    if any(not math.isclose(norm, 1.0, abs_tol=0.02) for norm in norms):
        raise RuntimeError("Embedding outputs are not L2-normalized")

    report: dict[str, object] = {
        "status": "ok",
        "python": platform.python_version(),
        "sentence_transformers": importlib.metadata.version("sentence-transformers"),
        "device_requested": device or "auto",
        "device_used": embeddings.device,
        "embedding": {
            "fingerprint": embedding_manifest["fingerprint"],
            "file_count": embedding_manifest["file_count"],
            "total_bytes": embedding_manifest["total_bytes"],
            "files": embedding_manifest["files"],
            "dimensions": len(vectors[0]),
            "normalized": True,
        },
    }

    if reranker_path is not None:
        reranker_manifest = build_model_manifest(reranker_path)
        reranker = SentenceTransformerRerankerProvider(
            str(reranker_path),
            fingerprint=str(reranker_manifest["fingerprint"]),
            device=device,
        )
        scores = reranker.rerank("exchange account risk", ["account risk limit"])
        if len(scores) != 1 or not math.isfinite(scores[0].score):
            raise RuntimeError("Reranker returned an invalid score")
        report["reranker"] = {
            "fingerprint": reranker_manifest["fingerprint"],
            "file_count": reranker_manifest["file_count"],
            "total_bytes": reranker_manifest["total_bytes"],
            "files": reranker_manifest["files"],
            "finite_score": True,
            "device_used": reranker.device,
        }
    import torch

    report["runtime"] = {
        "torch": importlib.metadata.version("torch"),
        "cuda_available": torch.cuda.is_available(),
        "mps_available": bool(
            getattr(
                getattr(torch.backends, "mps", None), "is_available", lambda: False
            )()
        ),
    }
    if torch.cuda.is_available():
        device_index = torch.cuda.current_device()
        free_bytes, total_bytes = torch.cuda.mem_get_info(device_index)
        report["runtime"]["cuda_device"] = torch.cuda.get_device_name(device_index)
        report["runtime"]["cuda_memory"] = {
            "total_bytes": total_bytes,
            "free_after_smoke_bytes": free_bytes,
            "allocated_after_smoke_bytes": torch.cuda.memory_allocated(device_index),
        }
    return report


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Hash and run local model artifacts without network access"
    )
    parser.add_argument("--embedding-model", required=True, type=Path)
    parser.add_argument("--reranker-model", type=Path)
    parser.add_argument("--device", choices=("cpu", "cuda", "mps"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    report = check_models(
        args.embedding_model,
        reranker_path=args.reranker_model,
        device=args.device,
    )
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
