from dataclasses import dataclass
from typing import Literal

AnswerMode = Literal["fast", "grounded"]


@dataclass(frozen=True, slots=True)
class Document:
    document_id: str
    source: str
    version: str
    content: str
    project_id: str = "default"


@dataclass(frozen=True, slots=True)
class Chunk:
    chunk_id: str
    document_id: str
    source: str
    version: str
    chunk_index: int
    start_line: int
    end_line: int
    content: str
    project_id: str = "default"


@dataclass(frozen=True, slots=True)
class SearchResult:
    chunk: Chunk
    score: float
    vector_score: float
    lexical_score: float


@dataclass(frozen=True, slots=True)
class Citation:
    document_id: str
    source: str
    version: str
    chunk_id: str
    start_line: int
    end_line: int
    text: str
    project_id: str = "default"


@dataclass(frozen=True, slots=True)
class RetrievalTraceItem:
    chunk_id: str
    source: str
    score: float
    vector_score: float
    lexical_score: float
    selected: bool
    project_id: str = "default"


@dataclass(frozen=True, slots=True)
class QueryResponse:
    answer: str
    citations: tuple[Citation, ...]
    retrieval: tuple[RetrievalTraceItem, ...]
    mode: AnswerMode
    refused: bool
    refusal_reason: str | None = None
