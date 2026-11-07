import argparse
import json
from dataclasses import asdict
from pathlib import Path

from local_coding_copilot.bootstrap import build_application
from local_coding_copilot.coding.models import CodingTask
from local_coding_copilot.coding.orchestrator import CodingOrchestrator
from local_coding_copilot.coding.patches import StaticPatchProvider
from local_coding_copilot.coding.sandbox import DockerSandbox
from local_coding_copilot.coding.worktree import GitWorktreeManager
from local_coding_copilot.rag.postgres import PostgresDocumentRepository
from local_coding_copilot.settings import api_token, database_dsn


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a verified coding task")
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--tasks", type=Path, default=Path("evals/coding_tasks.json"))
    parser.add_argument("--project-id", default="default")
    parser.add_argument("--base-commit")
    args = parser.parse_args()

    records = json.loads(args.tasks.read_text(encoding="utf-8"))
    record = next(
        (record for record in records if record["task_id"] == args.task_id), None
    )
    if record is None:
        raise ValueError(f"Unknown coding task: {args.task_id}")

    application = build_application()
    principal = application.auth.authenticate(api_token())
    orchestrator = CodingOrchestrator(
        worktrees=GitWorktreeManager(Path("data/runtime/worktrees")),
        sandbox=DockerSandbox(),
        patches=StaticPatchProvider.from_file(args.tasks),
        audit=PostgresDocumentRepository(database_dsn()),
    )
    result = orchestrator.run(
        args.repository,
        CodingTask(args.task_id, record["instructions"]),
        args.project_id,
        principal=principal,
        base_commit=args.base_commit,
        transport="cli",
    )
    print(json.dumps(asdict(result), ensure_ascii=False, indent=2))
    return 0 if result.status == "awaiting_review" else 2


if __name__ == "__main__":
    raise SystemExit(main())
