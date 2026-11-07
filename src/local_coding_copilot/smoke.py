import argparse
import json
from pathlib import Path

from local_coding_copilot.bootstrap import build_application
from local_coding_copilot.settings import api_token


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the document retrieval smoke set")
    parser.add_argument(
        "dataset", type=Path, nargs="?", default=Path("evals/document_smoke.json")
    )
    args = parser.parse_args()

    cases = json.loads(args.dataset.read_text(encoding="utf-8"))
    application = build_application()
    principal = application.auth.authenticate(api_token())
    failures = []
    for case in cases:
        response = application.service.query(
            case["question"], limit=3, principal=principal, transport="smoke"
        )
        sources = {citation.source for citation in response.citations}
        if case["expected_source"] not in sources:
            failures.append((case["question"], sorted(sources)))

    for question, sources in failures:
        print(f"FAIL: {question}; sources={sources}")
    print(f"Document smoke: {len(cases) - len(failures)}/{len(cases)} passed")
    return int(bool(failures))


if __name__ == "__main__":
    raise SystemExit(main())
