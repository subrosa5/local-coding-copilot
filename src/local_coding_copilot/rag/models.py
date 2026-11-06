from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Document:
    document_id: str
    source: str
    version: str
    content: str


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


@dataclass(frozen=True, slots=True)
class RetrievalTraceItem:
    chunk_id: str
    source: str
    score: float
    vector_score: float
    lexical_score: float


@dataclass(frozen=True, slots=True)
class QueryResponse:
    answer: str
    citations: tuple[Citation, ...]
    retrieval: tuple[RetrievalTraceItem, ...]
