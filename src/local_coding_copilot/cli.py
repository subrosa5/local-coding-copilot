import argparse
from collections.abc import Sequence

from local_coding_copilot.providers import FakeLLMProvider
from local_coding_copilot.service import CopilotService


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the local copilot smoke path")
    parser.add_argument("prompt", nargs="?", default="Hello")
    args = parser.parse_args(argv)

    service = CopilotService(llm=FakeLLMProvider())
    print(service.answer(args.prompt))
    return 0
