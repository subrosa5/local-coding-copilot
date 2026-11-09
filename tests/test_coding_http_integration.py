import subprocess
from collections.abc import Sequence
from pathlib import Path

from fake_inference import MOCK_NOTIONAL_DIFF, fake_inference_endpoint

from local_coding_copilot.auth import Principal
from local_coding_copilot.coding.models import CodingTask, SandboxResult
from local_coding_copilot.coding.orchestrator import CodingOrchestrator
from local_coding_copilot.coding.patches import ModelPatchProvider
from local_coding_copilot.coding.worktree import GitWorktreeManager
from local_coding_copilot.providers import OpenAICompatibleLLMProvider


class RecordingSandbox:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Path]] = []

    def run(self, worktree: Path, command: Sequence[str], stage: str) -> SandboxResult:
        self.calls.append((stage, worktree))
        return SandboxResult(
            stage=stage,
            command=tuple(command),
            exit_code=0,
            duration_ms=1,
            timed_out=False,
            stdout_tail="synthetic success",
            stderr_tail="",
        )


class RecordingAudit:
    def __init__(self) -> None:
        self.events: list[tuple[object, ...]] = []

    def record_audit(self, *args: object, **kwargs: object) -> None:
        self.events.append(args)


def test_fake_http_drives_model_patch_repair_worktree_sandbox_and_audit(
    exchange_repository: Path, tmp_path: Path, admin_principal: Principal
) -> None:
    sandbox = RecordingSandbox()
    audit = RecordingAudit()
    worktrees = GitWorktreeManager(tmp_path / "worktrees")
    base_commit = worktrees.resolve_base_commit(exchange_repository)
    original_source = (exchange_repository / "src/exchange_demo/orders.py").read_text()

    with fake_inference_endpoint(
        ("this mock response is not a diff", MOCK_NOTIONAL_DIFF)
    ) as (endpoint, requests):
        provider = OpenAICompatibleLLMProvider(endpoint, "test-only-mock-coder")
        result = CodingOrchestrator(
            worktrees=worktrees,
            sandbox=sandbox,
            patches=ModelPatchProvider(provider),
            audit=audit,
        ).run(
            exchange_repository,
            CodingTask(
                "notional-boundary",
                "Accept the synthetic exact boundary",
                context=("Synthetic source fixture",),
                context_commit_sha=base_commit,
            ),
            "default",
            principal=admin_principal,
            transport="test",
        )

        assert provider.stats.requests == 2
        assert provider.stats.failures == 0

    assert result.status == "awaiting_review"
    assert result.repair_iterations == 1
    assert result.patch_applied
    assert result.tests_changed
    assert result.changed_files == (
        "src/exchange_demo/orders.py",
        "tests/test_orders.py",
    )
    assert result.build is not None and result.build.exit_code == 0
    assert result.test is not None and result.test.exit_code == 0
    assert sandbox.calls == [
        ("build", Path(result.worktree)),
        ("test", Path(result.worktree)),
    ]
    assert Path(result.worktree).is_dir()
    assert (exchange_repository / "src/exchange_demo/orders.py").read_text() == (
        original_source
    )
    assert (
        subprocess.run(
            ["git", "-C", str(exchange_repository), "status", "--porcelain"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        == ""
    )

    assert len(requests) == 2
    assert all(request["path"] == "/v1/chat/completions" for request in requests)
    assert all(request["model"] == "test-only-mock-coder" for request in requests)
    repair_prompt = requests[1]["messages"][1]["content"]
    assert "Attempt: 2" in repair_prompt
    assert "Stage: patch_validation" in repair_prompt
    assert "expected only raw unified diff" in repair_prompt

    assert len(audit.events) == 1
    event = audit.events[0]
    assert event[4] == "awaiting_review"
    assert event[-1]["repair_iterations"] == 1
    assert event[-1]["diff_sha256"] == result.diff_sha256
    assert MOCK_NOTIONAL_DIFF not in str(event)
    assert "Accept the synthetic exact boundary" not in str(event)
