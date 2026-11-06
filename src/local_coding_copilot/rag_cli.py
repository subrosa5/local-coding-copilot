import argparse
import json
from dataclasses import asdict
from pathlib import Path

from local_coding_copilot.bootstrap import build_rag_service
from local_coding_copilot.ingestion import load_markdown_documents


def main() -> int:
    parser = argparse.ArgumentParser(description="Manage the local document RAG")
    commands = parser.add_subparsers(dest="command", required=True)

    ingest = commands.add_parser("ingest")
    ingest.add_argument("directory", type=Path)

    query = commands.add_parser("query")
    query.add_argument("question")
    query.add_argument("--limit", type=int, default=5)

    args = parser.parse_args()
    service = build_rag_service()

    if args.command == "ingest":
        documents = load_markdown_documents(args.directory)
        for document in documents:
            count = service.ingest_document(document)
            print(f"Indexed {document.source}: {count} chunks")
        print(f"Indexed {len(documents)} documents")
        return 0

    response = service.query(args.question, args.limit)
    print(json.dumps(asdict(response), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
