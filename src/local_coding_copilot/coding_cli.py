import argparse
import json
from dataclasses import asdict
from pathlib import Path

from local_coding_copilot.bootstrap import build_application
from local_coding_copilot.coding.context import load_full_code_context
from local_coding_copilot.coding.models import CodingTask
from local_coding_copilot.coding.orchestrator import CodingOrchestrator
from local_coding_copilot.coding.patches import ModelPatchProvider, StaticPatchProvider
from local_coding_copilot.coding.sandbox import DockerSandbox
from local_coding_copilot.coding.worktree import GitWorktreeManager
from local_coding_copilot.providers import FakeLLMProvider
from local_coding_copilot.rag.postgres import PostgresDocumentRepository
from local_coding_copilot.settings import api_token, database_dsn


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a verified coding task")
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--tasks", type=Path, default=Path("evals/coding_tasks.json"))
    parser.add_argument("--project-id", default="default")
    parser.add_argument("--base-commit")
    parser.add_argument("--patch-provider", choices=("llm", "static"), default="llm")
    parser.add_argument("--context-mode", choices=("rag", "base"), default="rag")
    args = parser.parse_args()

    records = json.loads(args.tasks.read_text(encoding="utf-8"))
    record = next(
        (record for record in records if record["task_id"] == args.task_id), None
    )
    if record is None:
        raise ValueError(f"Unknown coding task: {args.task_id}")

    application = build_application()
    principal = application.auth.authenticate(api_token())
    if args.patch_provider == "llm":
        if isinstance(application.llm, FakeLLMProvider):
            raise RuntimeError(
                "Configure a local endpoint with COPILOT_LLM_BASE_URL and "
                "COPILOT_LLM_MODEL, or select --patch-provider static explicitly"
            )
        patch_provider = ModelPatchProvider(application.llm)
    else:
        patch_provider = StaticPatchProvider.from_file(args.tasks)

    worktrees = GitWorktreeManager(Path("data/runtime/worktrees"))
    context: tuple[str, ...] = ()
    context_commit_sha = None
    if args.patch_provider == "llm" and args.context_mode == "rag":
        expected_base = worktrees.resolve_base_commit(args.repository, args.base_commit)
        retrieval = application.code_service.query(
            record["instructions"],
            limit=5,
            mode="grounded",
            principal=principal,
            project_id=args.project_id,
            transport="cli",
        )
        if retrieval.refused or not retrieval.citations:
            raise RuntimeError("Code RAG did not return grounded source context")
        commits = {citation.commit_sha for citation in retrieval.citations}
        if None in commits or len(commits) != 1:
            raise RuntimeError("Code RAG citations do not share a verified commit")
        context_commit_sha = next(iter(commits))
        if context_commit_sha != expected_base:
            raise RuntimeError(
                "Code RAG index does not match the requested base commit"
            )
        context = tuple(
            f"{citation.repository}/{citation.source}#{citation.symbol or 'module'}:"
            f"{citation.start_line}-{citation.end_line}@{citation.commit_sha}\n"
            f"{citation.text}"
            for citation in retrieval.citations
        )
    elif args.patch_provider == "llm" and args.context_mode == "base":
        context_commit_sha = worktrees.resolve_base_commit(
            args.repository, args.base_commit
        )
        context = load_full_code_context(args.repository, context_commit_sha)

    task = CodingTask(
        args.task_id,
        record["instructions"],
        context=context,
        context_commit_sha=context_commit_sha,
    )
    orchestrator = CodingOrchestrator(
        worktrees=worktrees,
        sandbox=DockerSandbox(),
        patches=patch_provider,
        audit=PostgresDocumentRepository(database_dsn()),
    )
    result = orchestrator.run(
        args.repository,
        task,
        args.project_id,
        principal=principal,
        base_commit=args.base_commit,
        transport="cli",
    )
    print(json.dumps(asdict(result), ensure_ascii=False, indent=2))
    return 0 if result.status == "awaiting_review" else 2


if __name__ == "__main__":
    raise SystemExit(main())
