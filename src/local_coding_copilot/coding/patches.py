from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol

from local_coding_copilot.coding.models import CodingTask, SandboxResult


class PatchProvider(Protocol):
    def propose_patch(
        self,
        task: CodingTask,
        attempt: int,
        previous_results: tuple[SandboxResult, ...],
    ) -> str: ...


class PatchUnavailableError(ValueError):
    pass


class StaticPatchProvider:
    def __init__(self, tasks: dict[str, tuple[str, ...]]) -> None:
        self._tasks = tasks

    @classmethod
    def from_file(cls, path: Path) -> StaticPatchProvider:
        records = json.loads(path.read_text(encoding="utf-8"))
        tasks = {}
        for record in records:
            patches = tuple(
                (path.parent / patch_file).read_text(encoding="utf-8")
                for patch_file in record["patch_files"]
            )
            if not record["task_id"] or not patches:
                raise ValueError("Each coding task needs an ID and at least one patch")
            tasks[record["task_id"]] = patches
        return cls(tasks)

    def propose_patch(
        self,
        task: CodingTask,
        attempt: int,
        previous_results: tuple[SandboxResult, ...],
    ) -> str:
        patches = self._tasks.get(task.task_id, ())
        if attempt >= len(patches):
            raise PatchUnavailableError(
                f"No patch for task {task.task_id} at attempt {attempt}"
            )
        return patches[attempt]
