import argparse
import json
from dataclasses import asdict
from pathlib import Path

from local_coding_copilot.bootstrap import build_application, build_code_indexer
from local_coding_copilot.settings import api_token


def main() -> int:
    parser = argparse.ArgumentParser(description="Index and query Python code")
    commands = parser.add_subparsers(dest="command", required=True)

    index = commands.add_parser("index")
    index.add_argument("directory", type=Path)
    index.add_argument("--repository", required=True)
    index.add_argument("--project-id", default="default")

    query = commands.add_parser("query")
    query.add_argument("question")
    query.add_argument("--limit", type=int, default=5)
    query.add_argument("--mode", choices=("fast", "grounded"), default="grounded")
    query.add_argument("--project-id", default="default")

    args = parser.parse_args()
    application = build_application()
    principal = application.auth.authenticate(api_token())

    if args.command == "index":
        indexer = application.code_indexer or build_code_indexer()
        result = indexer.index(
            args.directory,
            args.repository,
            args.project_id,
            principal=principal,
            transport="cli",
        )
        print(json.dumps(asdict(result), indent=2))
        return 0

    response = application.code_service.query(
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
