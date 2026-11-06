import re
from collections.abc import Sequence
from dataclasses import dataclass

from local_coding_copilot.rag.models import SearchResult

_CITATION = re.compile(r"\[(\d+)\]")
_NUMBER = re.compile(r"(?<![\w])\d+(?:[.,]\d+)*(?![\w])")


@dataclass(frozen=True, slots=True)
class GroundingResult:
    cited_indexes: tuple[int, ...]
    reason: str | None = None


def validate_grounding(answer: str, results: Sequence[SearchResult]) -> GroundingResult:
    if not results:
        return GroundingResult(cited_indexes=(), reason="no_relevant_evidence")

    cited_indexes = tuple(
        dict.fromkeys(int(value) for value in _CITATION.findall(answer))
    )
    if not cited_indexes:
        return GroundingResult(cited_indexes=(), reason="missing_citations")
    if any(index < 1 or index > len(results) for index in cited_indexes):
        return GroundingResult(cited_indexes=(), reason="invalid_citation")

    cited_evidence = "\n".join(
        results[index - 1].chunk.content for index in cited_indexes
    )
    answer_without_citations = _CITATION.sub("", answer)
    unsupported_numbers = [
        value
        for value in _NUMBER.findall(answer_without_citations)
        if _normalize_number(value) not in _numbers(cited_evidence)
    ]
    if unsupported_numbers:
        return GroundingResult(cited_indexes=(), reason="unsupported_number")
    return GroundingResult(cited_indexes=cited_indexes)


def _numbers(text: str) -> set[str]:
    return {_normalize_number(value) for value in _NUMBER.findall(text)}


def _normalize_number(value: str) -> str:
    return value.replace(",", "")
