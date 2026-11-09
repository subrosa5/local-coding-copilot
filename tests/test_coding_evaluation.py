import json
import subprocess
from pathlib import Path

import pytest

from local_coding_copilot.auth import Principal
from local_coding_copilot.coding.context import load_full_code_context
from local_coding_copilot.coding.models import CodingTask, SandboxResult
from local_coding_copilot.coding.worktree import GitWorktreeManager
from local_coding_copilot.coding_evaluation import (
    load_benchmark_tasks,
    run_coding_benchmark,
)
from local_coding_copilot.models import ChatResponse
from local_coding_copilot.rag.models import Citation, QueryResponse

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PATCH = (PROJECT_ROOT / "evals/coding_patches/notional-boundary.patch").read_text(
    encoding="utf-8"
)


class StubLLM:
    def __init__(self) -> None:
        self.requests = []

    def complete(self, request) -> ChatResponse:
        self.requests.append(request)
        return ChatResponse(content=PATCH)


class StubCodeService:
    def __init__(self, commit_sha: str) -> None:
        self.commit_sha = commit_sha
        self.queries: list[str] = []

    def query(
        self, question, limit, mode, *, principal, project_id, transport
    ) -> QueryResponse:
        self.queries.append(question)
        citation = Citation(
            document_id="code",
            source="src/exchange_demo/orders.py",
            version=self.commit_sha,
            chunk_id="orders",
            start_line=1,
            end_line=2,
            text="synthetic code context",
            project_id=project_id,
            repository="exchange-demo",
            symbol="validate_order",
            commit_sha=self.commit_sha,
        )
        return QueryResponse(
            answer="Evidence [1]",
            citations=(citation,),
            retrieval=(),
            mode="grounded",
            refused=False,
        )


class StubSandbox:
    def run(self, worktree, command, stage) -> SandboxResult:
        return SandboxResult(stage, tuple(command), 0, 1, False, "", "")


class StubAudit:
    def record_audit(self, *args, **kwargs) -> None:
        return


def test_benchmark_task_loader_rejects_gold_patch_fields(tmp_path: Path) -> None:
    dataset = tmp_path / "tasks.json"
    dataset.write_text(
        json.dumps(
            [
                {
                    "task_id": "task",
                    "instructions": "Fix behavior",
                    "patch_files": ["answer.patch"],
                }
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="task_id and instructions only"):
        load_benchmark_tasks(dataset)


def test_base_context_uses_exact_tracked_source_from_git_commit(
    exchange_repository: Path,
) -> None:
    commit = subprocess.run(
        ["git", "-C", str(exchange_repository), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    context = load_full_code_context(exchange_repository, commit)

    assert any("src/exchange_demo/orders.py@" + commit in item for item in context)
    assert any("MAX_ORDER_NOTIONAL" in item for item in context)
    assert any("test_notional_boundary_is_accepted" in item for item in context)


def test_coding_benchmark_runs_three_configs_without_changing_source(
    exchange_repository: Path, tmp_path: Path
) -> None:
    commit = subprocess.run(
        ["git", "-C", str(exchange_repository), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    service = StubCodeService(commit)
    llm = StubLLM()
    report = run_coding_benchmark(
        exchange_repository,
        (CodingTask("notional-boundary", "Fix boundary"),),
        llm=llm,
        code_service=service,
        worktrees=GitWorktreeManager(tmp_path / "worktrees"),
        sandbox=StubSandbox(),
        audit=StubAudit(),
        principal=Principal("admin", "admin", frozenset({"default"})),
        project_id="default",
    )

    assert [item["name"] for item in report["configurations"]] == [
        "base",
        "rag",
        "rag_test_loop",
    ]
    assert all(item["task_success"] == 1 for item in report["configurations"])
    assert report["gold_patch_files_loaded"] is False
    assert report["human_acceptance"] is None
    assert report["base_context"] == "full_tracked_python_snapshot"
    assert report["llm_provider"]["type"] == "StubLLM"
    assert service.queries == ["Fix boundary", "Fix boundary"]
    base_prompt = llm.requests[0].messages[1].content
    rag_prompt = llm.requests[1].messages[1].content
    assert "src/exchange_demo/orders.py@" + commit in base_prompt
    assert "synthetic code context" not in base_prompt
    assert "synthetic code context" in rag_prompt
    assert (
        subprocess.run(
            ["git", "-C", str(exchange_repository), "status", "--porcelain"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        == ""
    )
    assert list((tmp_path / "worktrees").iterdir()) == []


def test_benchmark_records_called_process_error_during_cleanup(
    exchange_repository: Path, tmp_path: Path
) -> None:
    commit = subprocess.run(
        ["git", "-C", str(exchange_repository), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    worktrees = GitWorktreeManager(tmp_path / "worktrees")
    remove_worktree = worktrees.remove

    def remove_then_raise(repository: Path, worktree_path: Path) -> None:
        remove_worktree(repository, worktree_path)
        raise subprocess.CalledProcessError(1, ["git", "worktree", "remove"])

    worktrees.remove = remove_then_raise
    report = run_coding_benchmark(
        exchange_repository,
        (CodingTask("notional-boundary", "Fix boundary"),),
        llm=StubLLM(),
        code_service=StubCodeService(commit),
        worktrees=worktrees,
        sandbox=StubSandbox(),
        audit=StubAudit(),
        principal=Principal("admin", "admin", frozenset({"default"})),
        project_id="default",
    )

    configs = report["configurations"]
    assert len(configs) == 3
    assert all(
        item["results"][0]["worktree_cleanup_error"] == "CalledProcessError"
        for item in configs
    )
    assert list((tmp_path / "worktrees").iterdir()) == []
