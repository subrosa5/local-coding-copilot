import hashlib
import subprocess
from collections.abc import Sequence
from pathlib import Path

import pytest

from local_coding_copilot.auth import AuthorizationError, Principal
from local_coding_copilot.coding.models import CodingTask, SandboxResult
from local_coding_copilot.coding.orchestrator import CodingOrchestrator
from local_coding_copilot.coding.patches import StaticPatchProvider
from local_coding_copilot.coding.worktree import GitWorktreeManager, PatchRejectedError

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TASKS_PATH = PROJECT_ROOT / "evals" / "coding_tasks.json"


class RecordingAudit:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []

    def record_audit(self, *args: object, **kwargs: object) -> None:
        self.events.append({"args": args, "kwargs": kwargs})


class FakeSandbox:
    def __init__(
        self,
        build_exit_codes: Sequence[int] = (),
        test_exit_codes: Sequence[int] = (),
    ) -> None:
        self._exit_codes = {
            "build": list(build_exit_codes),
            "test": list(test_exit_codes),
        }
        self.calls: list[tuple[str, Path]] = []

    def run(self, worktree: Path, command: Sequence[str], stage: str) -> SandboxResult:
        self.calls.append((stage, worktree))
        exit_codes = self._exit_codes[stage]
        exit_code = exit_codes.pop(0) if exit_codes else 0
        return SandboxResult(
            stage=stage,
            command=tuple(command),
            exit_code=exit_code,
            duration_ms=1,
            timed_out=False,
            stdout_tail="",
            stderr_tail="",
        )


def git(repository: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repository), *arguments],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def make_orchestrator(
    tmp_path: Path,
    sandbox: FakeSandbox,
    patches: StaticPatchProvider,
    audit: RecordingAudit,
) -> CodingOrchestrator:
    return CodingOrchestrator(
        worktrees=GitWorktreeManager(tmp_path / "worktrees"),
        sandbox=sandbox,
        patches=patches,
        audit=audit,
    )


def test_worktree_applies_patch_without_changing_source(
    exchange_repository: Path, tmp_path: Path
) -> None:
    manager = GitWorktreeManager(tmp_path / "worktrees")
    base_commit = git(exchange_repository, "rev-parse", "HEAD")
    original = (exchange_repository / "src/exchange_demo/orders.py").read_text()
    patch = StaticPatchProvider.from_file(TASKS_PATH).propose_patch(
        CodingTask("notional-boundary", ""), 0, ()
    )

    worktree = manager.create(exchange_repository, base_commit)
    manager.apply_patch(worktree, patch)

    assert worktree.base_commit == base_commit
    assert git(worktree.path, "rev-parse", "HEAD") == base_commit
    assert (exchange_repository / "src/exchange_demo/orders.py").read_text() == original
    assert "order.quantity > MAX_ORDER_NOTIONAL" in manager.diff(worktree)
    assert manager.changed_files(worktree) == (
        "src/exchange_demo/orders.py",
        "tests/test_orders.py",
    )


def test_worktree_rejects_dirty_source(
    exchange_repository: Path, tmp_path: Path
) -> None:
    (exchange_repository / "src/exchange_demo/orders.py").write_text(
        "UNCOMMITTED = True\n", encoding="utf-8"
    )

    with pytest.raises(ValueError, match="clean Git worktree"):
        GitWorktreeManager(tmp_path / "worktrees").create(exchange_repository)


def test_worktree_rejects_non_applicable_patch(
    exchange_repository: Path, tmp_path: Path
) -> None:
    manager = GitWorktreeManager(tmp_path / "worktrees")
    worktree = manager.create(exchange_repository)

    with pytest.raises(PatchRejectedError, match="does not apply"):
        manager.apply_patch(worktree, "not a unified diff")

    assert manager.diff(worktree) == ""


def test_worktree_rejects_patch_targeting_symlink(
    exchange_repository: Path, tmp_path: Path
) -> None:
    manager = GitWorktreeManager(tmp_path / "worktrees")
    worktree = manager.create(exchange_repository)
    alias = worktree.path / "src/exchange_demo/alias.py"
    alias.symlink_to("orders.py")
    patch = (
        "diff --git a/src/exchange_demo/alias.py b/src/exchange_demo/alias.py\n"
        "--- a/src/exchange_demo/alias.py\n"
        "+++ b/src/exchange_demo/alias.py\n"
        "@@ -1 +1 @@\n"
        "-old\n+new\n"
    )

    with pytest.raises(PatchRejectedError, match="symlink"):
        manager.apply_patch(worktree, patch)


def test_static_patch_provider_loads_all_prepared_tasks() -> None:
    provider = StaticPatchProvider.from_file(TASKS_PATH)

    for task_id in ("notional-boundary", "price-time-priority", "stale-threshold"):
        patch = provider.propose_patch(CodingTask(task_id, ""), 0, ())
        assert patch.startswith("diff --git")
        assert "@unittest.expectedFailure" in patch


def test_verified_patch_waits_for_human_review(
    exchange_repository: Path, tmp_path: Path, admin_principal: Principal
) -> None:
    audit = RecordingAudit()
    result = make_orchestrator(
        tmp_path,
        FakeSandbox(),
        StaticPatchProvider.from_file(TASKS_PATH),
        audit,
    ).run(
        exchange_repository,
        CodingTask("notional-boundary", "Accept the exact boundary"),
        "default",
        principal=admin_principal,
    )

    assert result.status == "awaiting_review"
    assert result.repair_iterations == 0
    assert result.build is not None and result.build.exit_code == 0
    assert result.test is not None and result.test.exit_code == 0
    assert result.diff_sha256 == hashlib.sha256(result.diff.encode()).hexdigest()
    assert result.changed_files == (
        "src/exchange_demo/orders.py",
        "tests/test_orders.py",
    )
    assert result.tests_changed
    assert audit.events[-1]["args"][4] == "awaiting_review"
    assert result.diff not in str(audit.events)


def test_orchestrator_stops_after_two_repairs(
    exchange_repository: Path, tmp_path: Path, admin_principal: Principal
) -> None:
    patch = StaticPatchProvider.from_file(TASKS_PATH).propose_patch(
        CodingTask("notional-boundary", ""), 0, ()
    )
    sandbox = FakeSandbox(build_exit_codes=[0, 0, 0], test_exit_codes=[1, 1, 1])
    result = make_orchestrator(
        tmp_path,
        sandbox,
        StaticPatchProvider({"notional-boundary": (patch, patch, patch)}),
        RecordingAudit(),
    ).run(
        exchange_repository,
        CodingTask("notional-boundary", ""),
        "default",
        principal=admin_principal,
    )

    assert result.status == "failed"
    assert result.repair_iterations == 2
    assert len(sandbox.calls) == 6


def test_repairs_can_recover_from_build_and_test_failures(
    exchange_repository: Path, tmp_path: Path, admin_principal: Principal
) -> None:
    patch = StaticPatchProvider.from_file(TASKS_PATH).propose_patch(
        CodingTask("notional-boundary", ""), 0, ()
    )
    sandbox = FakeSandbox(build_exit_codes=[1, 0, 0], test_exit_codes=[1, 0])
    result = make_orchestrator(
        tmp_path,
        sandbox,
        StaticPatchProvider({"notional-boundary": (patch, patch, patch)}),
        RecordingAudit(),
    ).run(
        exchange_repository,
        CodingTask("notional-boundary", ""),
        "default",
        principal=admin_principal,
    )

    assert result.status == "awaiting_review"
    assert result.repair_iterations == 2
    assert len(sandbox.calls) == 5


def test_failed_build_does_not_reuse_previous_test_result(
    exchange_repository: Path, tmp_path: Path, admin_principal: Principal
) -> None:
    patch = StaticPatchProvider.from_file(TASKS_PATH).propose_patch(
        CodingTask("notional-boundary", ""), 0, ()
    )
    sandbox = FakeSandbox(build_exit_codes=[0, 1, 1], test_exit_codes=[1])
    result = make_orchestrator(
        tmp_path,
        sandbox,
        StaticPatchProvider({"notional-boundary": (patch, patch, patch)}),
        RecordingAudit(),
    ).run(
        exchange_repository,
        CodingTask("notional-boundary", ""),
        "default",
        principal=admin_principal,
    )

    assert result.status == "failed"
    assert result.build is not None and result.build.exit_code == 1
    assert result.test is None
    assert result.repair_iterations == 2


def test_missing_patch_returns_failed_without_running_sandbox(
    exchange_repository: Path, tmp_path: Path, admin_principal: Principal
) -> None:
    sandbox = FakeSandbox()
    result = make_orchestrator(
        tmp_path, sandbox, StaticPatchProvider({}), RecordingAudit()
    ).run(
        exchange_repository,
        CodingTask("unknown", ""),
        "default",
        principal=admin_principal,
    )

    assert result.status == "failed"
    assert result.repair_iterations == 0
    assert result.build is None and result.test is None
    assert sandbox.calls == []


def test_invalid_patch_is_reported_to_bounded_repair_attempt(
    exchange_repository: Path, tmp_path: Path, admin_principal: Principal
) -> None:
    valid_patch = StaticPatchProvider.from_file(TASKS_PATH).propose_patch(
        CodingTask("notional-boundary", ""), 0, ()
    )

    class RepairProvider:
        def __init__(self) -> None:
            self.feedback: list[tuple[SandboxResult, ...]] = []

        def propose_patch(self, task, attempt, previous_results):
            self.feedback.append(previous_results)
            return "not a unified diff" if attempt == 0 else valid_patch

    patches = RepairProvider()
    result = make_orchestrator(tmp_path, FakeSandbox(), patches, RecordingAudit()).run(
        exchange_repository,
        CodingTask("notional-boundary", ""),
        "default",
        principal=admin_principal,
    )

    assert result.status == "awaiting_review"
    assert result.patch_applied
    assert result.repair_iterations == 1
    assert patches.feedback[0] == ()
    assert patches.feedback[1][0].stage == "patch_validation"
    assert "raw unified diff" in patches.feedback[1][0].stderr_tail


@pytest.mark.parametrize(
    "principal, reason",
    [
        (Principal("viewer", "viewer", frozenset({"default"})), "admin_role_required"),
        (
            Principal("outsider", "admin", frozenset({"other"})),
            "project_membership_required",
        ),
    ],
)
def test_coding_task_authorization_precedes_worktree_creation(
    exchange_repository: Path,
    tmp_path: Path,
    principal: Principal,
    reason: str,
) -> None:
    audit = RecordingAudit()
    runtime = tmp_path / "worktrees"
    orchestrator = CodingOrchestrator(
        worktrees=GitWorktreeManager(runtime),
        sandbox=FakeSandbox(),
        patches=StaticPatchProvider.from_file(TASKS_PATH),
        audit=audit,
    )

    with pytest.raises(AuthorizationError, match=reason):
        orchestrator.run(
            exchange_repository,
            CodingTask("notional-boundary", ""),
            "default",
            principal=principal,
        )

    assert not runtime.exists()
    assert audit.events[-1]["args"][4] == "denied"
