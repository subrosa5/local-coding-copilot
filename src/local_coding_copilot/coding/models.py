from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True, slots=True)
class CodingTask:
    task_id: str
    instructions: str
    context: tuple[str, ...] = ()
    context_commit_sha: str | None = None


@dataclass(frozen=True, slots=True)
class SandboxResult:
    stage: str
    command: tuple[str, ...]
    exit_code: int
    duration_ms: int
    timed_out: bool
    stdout_tail: str
    stderr_tail: str


@dataclass(frozen=True, slots=True)
class CodingTaskResult:
    task_id: str
    status: Literal["awaiting_review", "failed"]
    worktree: str
    base_commit: str
    diff: str
    diff_sha256: str
    changed_files: tuple[str, ...]
    tests_changed: bool
    repair_iterations: int
    build: SandboxResult | None
    test: SandboxResult | None
    message: str
    patch_applied: bool = False
