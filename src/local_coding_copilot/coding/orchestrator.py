import hashlib
from collections.abc import Sequence
from pathlib import Path

from local_coding_copilot.auth import (
    AuthenticationError,
    AuthorizationError,
    Principal,
)
from local_coding_copilot.coding.models import (
    CodingTask,
    CodingTaskResult,
    SandboxResult,
)
from local_coding_copilot.coding.patches import PatchProvider, PatchUnavailableError
from local_coding_copilot.coding.sandbox import DockerSandbox
from local_coding_copilot.coding.worktree import (
    GitWorktreeManager,
    PatchRejectedError,
    Worktree,
)
from local_coding_copilot.rag.postgres import PostgresDocumentRepository


class CodingOrchestrator:
    def __init__(
        self,
        worktrees: GitWorktreeManager,
        sandbox: DockerSandbox,
        patches: PatchProvider,
        audit: PostgresDocumentRepository,
        max_repair_iterations: int = 2,
        build_command: Sequence[str] = ("python", "-m", "compileall", "-q", "src"),
        test_command: Sequence[str] = (
            "python",
            "-m",
            "unittest",
            "discover",
            "-s",
            "tests",
            "-v",
        ),
    ) -> None:
        if not 0 <= max_repair_iterations <= 2:
            raise ValueError("Repair iterations must be between 0 and 2")
        self._worktrees = worktrees
        self._sandbox = sandbox
        self._patches = patches
        self._audit = audit
        self._max_repair_iterations = max_repair_iterations
        self._build_command = tuple(build_command)
        self._test_command = tuple(test_command)

    def run(
        self,
        repository: Path,
        task: CodingTask,
        project_id: str,
        *,
        principal: Principal | None,
        base_commit: str | None = None,
        transport: str = "internal",
    ) -> CodingTaskResult:
        self._authorize(principal, project_id, transport)
        worktree = self._worktrees.create(repository, base_commit)
        previous_results = []
        build = None
        test = None
        message = "Patch did not pass verification"

        for attempt in range(self._max_repair_iterations + 1):
            build = None
            test = None
            if attempt:
                self._worktrees.reset(worktree)
            try:
                patch = self._patches.propose_patch(
                    task, attempt, tuple(previous_results)
                )
                self._worktrees.apply_patch(worktree, patch)
            except PatchUnavailableError as error:
                message = str(error)
                break
            except PatchRejectedError as error:
                message = str(error)
                continue

            build = self._sandbox.run(worktree.path, self._build_command, "build")
            previous_results.append(build)
            if build.exit_code == 0:
                test = self._sandbox.run(worktree.path, self._test_command, "test")
                previous_results.append(test)
            if build.exit_code == 0 and test is not None and test.exit_code == 0:
                message = "Verified patch is waiting for human review"
                return self._result(
                    task,
                    worktree,
                    "awaiting_review",
                    attempt,
                    build,
                    test,
                    message,
                    principal,
                    project_id,
                    transport,
                )

        return self._result(
            task,
            worktree,
            "failed",
            attempt,
            build,
            test,
            message,
            principal,
            project_id,
            transport,
        )

    def _result(
        self,
        task: CodingTask,
        worktree: Worktree,
        status: str,
        repair_iterations: int,
        build: SandboxResult | None,
        test: SandboxResult | None,
        message: str,
        principal: Principal,
        project_id: str,
        transport: str,
    ) -> CodingTaskResult:
        diff = self._worktrees.diff(worktree)
        changed_files = self._worktrees.changed_files(worktree)
        diff_sha256 = hashlib.sha256(diff.encode()).hexdigest()
        tests_changed = any(
            path == "tests" or path.startswith("tests/") for path in changed_files
        )
        result = CodingTaskResult(
            task_id=task.task_id,
            status=status,
            worktree=str(worktree.path),
            base_commit=worktree.base_commit,
            diff=diff,
            diff_sha256=diff_sha256,
            changed_files=changed_files,
            tests_changed=tests_changed,
            repair_iterations=repair_iterations,
            build=build,
            test=test,
            message=message,
        )
        self._audit.record_audit(
            principal.user_id,
            project_id,
            "coding_task",
            transport,
            status,
            None if status == "awaiting_review" else "verification_failed",
            {
                "task_id": task.task_id,
                "base_commit": worktree.base_commit,
                "diff_sha256": diff_sha256,
                "changed_files": len(changed_files),
                "tests_changed": tests_changed,
                "repair_iterations": repair_iterations,
            },
        )
        return result

    def _authorize(
        self, principal: Principal | None, project_id: str, transport: str
    ) -> None:
        if principal is None:
            raise AuthenticationError("An authenticated principal is required")
        reason = None
        if project_id not in principal.project_ids:
            reason = "project_membership_required"
        elif principal.role != "admin":
            reason = "admin_role_required"
        if reason:
            self._audit.record_audit(
                principal.user_id,
                project_id,
                "coding_task",
                transport,
                "denied",
                reason,
            )
            raise AuthorizationError(reason)
