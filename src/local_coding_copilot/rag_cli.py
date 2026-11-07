import argparse
import json
from dataclasses import asdict, replace
from pathlib import Path

from local_coding_copilot.bootstrap import build_application
from local_coding_copilot.ingestion import load_markdown_documents
from local_coding_copilot.settings import api_token


def main() -> int:
    parser = argparse.ArgumentParser(description="Manage the local document RAG")
    commands = parser.add_subparsers(dest="command", required=True)

    ingest = commands.add_parser("ingest")
    ingest.add_argument("directory", type=Path)
    ingest.add_argument("--project-id", default="default")

    query = commands.add_parser("query")
    query.add_argument("question")
    query.add_argument("--limit", type=int, default=5)
    query.add_argument("--mode", choices=("fast", "grounded"), default="grounded")
    query.add_argument("--project-id", default="default")

    args = parser.parse_args()
    application = build_application()
    principal = application.auth.authenticate(api_token())

    if args.command == "ingest":
        documents = load_markdown_documents(args.directory)
        for document in documents:
            count = application.service.ingest_document(
                replace(document, project_id=args.project_id),
                principal=principal,
                transport="cli",
            )
            print(f"Indexed {document.source}: {count} chunks")
        print(f"Indexed {len(documents)} documents")
        return 0

    response = application.service.query(
        args.question,
        args.limit,
        args.mode,
        principal=principal,
        project_id=args.project_id,
        transport="cli",
    )
    print(json.dumps(asdict(response), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
