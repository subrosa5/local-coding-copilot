"""Run local coding comparisons without exposing prepared patches to the model."""

import argparse
import hashlib
import json
import subprocess
from dataclasses import asdict
from math import ceil
from pathlib import Path
from time import perf_counter
from typing import Protocol

from local_coding_copilot.auth import Principal
from local_coding_copilot.coding.context import load_full_code_context
from local_coding_copilot.coding.models import CodingTask
from local_coding_copilot.coding.orchestrator import CodingOrchestrator
from local_coding_copilot.coding.patches import ModelPatchProvider
from local_coding_copilot.coding.sandbox import DockerSandbox
from local_coding_copilot.coding.worktree import GitWorktreeManager
from local_coding_copilot.providers import LLMProvider
from local_coding_copilot.providers.openai_compatible import (
    OpenAICompatibleLLMProvider,
)
from local_coding_copilot.rag.models import QueryResponse
from local_coding_copilot.rag.postgres import PostgresDocumentRepository
from local_coding_copilot.settings import api_token, database_dsn


class CodeQueryService(Protocol):
    def query(
        self,
        question: str,
        limit: int,
        mode: str,
        *,
        principal: Principal,
        project_id: str,
        transport: str,
    ) -> QueryResponse: ...


def load_benchmark_tasks(path: Path) -> tuple[CodingTask, ...]:
    records = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(records, list) or not records:
        raise ValueError("Coding benchmark must contain a non-empty task list")
    tasks = []
    seen: set[str] = set()
    for record in records:
        if (
            not isinstance(record, dict)
            or set(record) != {"task_id", "instructions"}
            or not isinstance(record["task_id"], str)
            or not isinstance(record["instructions"], str)
            or not record["task_id"].strip()
            or not record["instructions"].strip()
            or record["task_id"] in seen
        ):
            raise ValueError(
                "Benchmark records must have unique task_id and instructions only"
            )
        seen.add(record["task_id"])
        tasks.append(CodingTask(record["task_id"], record["instructions"]))
    return tuple(tasks)


def run_coding_benchmark(
    repository: Path,
    tasks: tuple[CodingTask, ...],
    *,
    llm: LLMProvider,
    code_service: CodeQueryService,
    worktrees: GitWorktreeManager,
    sandbox: DockerSandbox,
    audit: PostgresDocumentRepository,
    principal: Principal,
    project_id: str,
) -> dict[str, object]:
    base_commit = worktrees.resolve_base_commit(repository)
    configurations = (
        ("base", False, 0),
        ("rag", True, 0),
        ("rag_test_loop", True, 2),
    )
    reports = []
    for name, use_rag, max_repairs in configurations:
        provider_before = _provider_stats(llm)
        task_results = []
        baseline_context = (
            load_full_code_context(repository, base_commit) if name == "base" else ()
        )
        for source_task in tasks:
            started = perf_counter()
            task = (
                CodingTask(
                    source_task.task_id,
                    source_task.instructions,
                    context=baseline_context,
                    context_commit_sha=base_commit,
                )
                if name == "base"
                else source_task
            )
            if use_rag:
                try:
                    task = _with_code_context(
                        source_task,
                        code_service,
                        principal,
                        project_id,
                        base_commit,
                    )
                except (RuntimeError, ValueError) as error:
                    task_results.append(
                        {
                            "task_id": source_task.task_id,
                            "status": "retrieval_failed",
                            "error_type": type(error).__name__,
                            "duration_ms": round((perf_counter() - started) * 1000),
                        }
                    )
                    continue

            orchestrator = CodingOrchestrator(
                worktrees=worktrees,
                sandbox=sandbox,
                patches=ModelPatchProvider(llm),
                audit=audit,
                max_repair_iterations=max_repairs,
            )
            result = None
            try:
                result = orchestrator.run(
                    repository,
                    task,
                    project_id,
                    principal=principal,
                    base_commit=base_commit,
                    transport="coding-evaluation",
                )
            except (RuntimeError, ValueError) as error:
                task_results.append(
                    {
                        "task_id": source_task.task_id,
                        "status": "run_failed",
                        "error_type": type(error).__name__,
                        "duration_ms": round((perf_counter() - started) * 1000),
                    }
                )
                continue
            if result is not None:
                try:
                    worktrees.remove(repository, Path(result.worktree))
                    cleanup_error = None
                except (OSError, ValueError, subprocess.SubprocessError) as error:
                    cleanup_error = type(error).__name__
                task_results.append(
                    {
                        "task_id": result.task_id,
                        "status": result.status,
                        "patch_applied": result.patch_applied,
                        "build_passed": result.build is not None
                        and result.build.exit_code == 0,
                        "test_passed": result.test is not None
                        and result.test.exit_code == 0,
                        "repair_iterations": result.repair_iterations,
                        "tests_changed": result.tests_changed,
                        "diff_sha256": result.diff_sha256,
                        "duration_ms": round((perf_counter() - started) * 1000),
                        "worktree_cleanup_error": cleanup_error,
                    }
                )
        provider_after = _provider_stats(llm)
        reports.append(
            _summarize(
                name,
                task_results,
                provider_before,
                provider_after,
                base_commit,
            )
        )
    return {
        "schema_version": 1,
        "base_commit": base_commit,
        "benchmark_sha256": _benchmark_fingerprint(tasks),
        "llm_provider": {
            "type": (
                "openai-compatible-local"
                if isinstance(llm, OpenAICompatibleLLMProvider)
                else type(llm).__name__
            ),
            "configured_model": llm.model_name
            if isinstance(llm, OpenAICompatibleLLMProvider)
            else None,
            "endpoint": llm.endpoint_url
            if isinstance(llm, OpenAICompatibleLLMProvider)
            else None,
            "max_tokens": llm.max_tokens
            if isinstance(llm, OpenAICompatibleLLMProvider)
            else None,
        },
        "task_count": len(tasks),
        "base_context": "full_tracked_python_snapshot",
        "gold_patch_files_loaded": False,
        "human_acceptance": None,
        "configurations": reports,
    }


def _benchmark_fingerprint(tasks: tuple[CodingTask, ...]) -> str:
    canonical = json.dumps(
        [
            {"task_id": task.task_id, "instructions": task.instructions}
            for task in tasks
        ],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _with_code_context(
    task: CodingTask,
    service: CodeQueryService,
    principal: Principal,
    project_id: str,
    base_commit: str,
) -> CodingTask:
    response = service.query(
        task.instructions,
        5,
        "grounded",
        principal=principal,
        project_id=project_id,
        transport="coding-evaluation",
    )
    if response.refused or not response.citations:
        raise ValueError("Code RAG returned no grounded evidence")
    if any(citation.commit_sha != base_commit for citation in response.citations):
        raise ValueError("Code RAG evidence does not match the benchmark base commit")
    return CodingTask(
        task.task_id,
        task.instructions,
        context=tuple(
            f"{citation.repository}/{citation.source}#{citation.symbol or 'module'}:"
            f"{citation.start_line}-{citation.end_line}@{citation.commit_sha}\n"
            f"{citation.text}"
            for citation in response.citations
        ),
        context_commit_sha=base_commit,
    )


def _provider_stats(llm: LLMProvider) -> dict[str, object] | None:
    if not isinstance(llm, OpenAICompatibleLLMProvider):
        return None
    return asdict(llm.stats)


def _summarize(
    name: str,
    results: list[dict[str, object]],
    before: dict[str, object] | None,
    after: dict[str, object] | None,
    base_commit: str,
) -> dict[str, object]:
    count = len(results)
    passed = sum(result.get("status") == "awaiting_review" for result in results)
    applied = sum(result.get("patch_applied") is True for result in results)
    builds = sum(result.get("build_passed") is True for result in results)
    tests = sum(result.get("test_passed") is True for result in results)
    durations = [int(result["duration_ms"]) for result in results]
    repairs = sum(int(result.get("repair_iterations", 0)) for result in results)
    metrics = _stats_delta(before, after)
    completion_tokens = metrics.get("completion_tokens") if metrics else None
    latency_ms = metrics.get("latency_ms_total") if metrics else None
    latency_samples = metrics.get("latency_samples_ms") if metrics else None
    tokens_per_second = None
    if (
        isinstance(completion_tokens, int)
        and isinstance(latency_ms, (int, float))
        and latency_ms > 0
    ):
        tokens_per_second = round(completion_tokens / (latency_ms / 1000), 2)
    return {
        "name": name,
        "base_commit": base_commit,
        "task_success": passed,
        "task_success_rate": _rate(passed, count),
        "pass_at_1": _rate(passed, count) if name in {"base", "rag"} else None,
        "success_after_repairs": passed if name == "rag_test_loop" else None,
        "patch_apply_rate": _rate(applied, count),
        "build_pass_rate": _rate(builds, count),
        "test_pass_rate": _rate(tests, count),
        "repair_iterations": repairs,
        "mean_task_duration_ms": round(sum(durations) / count) if count else None,
        "llm": metrics,
        "tokens_per_second": tokens_per_second,
        "llm_latency_p50_ms": _percentile(latency_samples, 0.50),
        "llm_latency_p95_ms": _percentile(latency_samples, 0.95),
        "results": results,
    }


def _stats_delta(
    before: dict[str, object] | None, after: dict[str, object] | None
) -> dict[str, object] | None:
    if before is None or after is None:
        return None
    delta: dict[str, object] = {}
    for key in ("requests", "failures", "latency_ms_total"):
        delta[key] = after[key] - before[key]
    before_samples = before["latency_samples_ms"]
    after_samples = after["latency_samples_ms"]
    if isinstance(before_samples, tuple) and isinstance(after_samples, tuple):
        previous_calls = int(before["requests"]) + int(before["failures"])
        delta["latency_samples_ms"] = after_samples[previous_calls:]
    for key in ("prompt_tokens", "completion_tokens"):
        delta[key] = (
            after[key] - before[key]
            if isinstance(after[key], int) and isinstance(before[key], int)
            else None
        )
    return delta


def _rate(value: int, total: int) -> float | None:
    return round(value / total, 4) if total else None


def _percentile(samples: object, quantile: float) -> float | None:
    if not isinstance(samples, tuple) or not samples:
        return None
    values = sorted(float(value) for value in samples)
    index = min(len(values) - 1, max(0, ceil(len(values) * quantile) - 1))
    return round(values[index], 2)


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare local coding configurations")
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument(
        "--tasks", type=Path, default=Path("evals/coding_benchmark.json")
    )
    parser.add_argument("--project-id", default="default")
    parser.add_argument(
        "--output", type=Path, default=Path("data/runtime/m7-coding-evaluation.json")
    )
    args = parser.parse_args()

    from local_coding_copilot.bootstrap import build_application

    application = build_application()
    if not isinstance(application.llm, OpenAICompatibleLLMProvider):
        raise RuntimeError("Configure the local OpenAI-compatible endpoint first")
    principal = application.auth.authenticate(api_token())
    audit = PostgresDocumentRepository(database_dsn())
    runtime = Path("data/runtime/m7-worktrees")
    result = run_coding_benchmark(
        args.repository,
        load_benchmark_tasks(args.tasks),
        llm=application.llm,
        code_service=application.code_service,
        worktrees=GitWorktreeManager(runtime),
        sandbox=DockerSandbox(),
        audit=audit,
        principal=principal,
        project_id=args.project_id,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
