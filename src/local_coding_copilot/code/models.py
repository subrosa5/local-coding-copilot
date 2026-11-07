from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CodeChunk:
    chunk_id: str
    project_id: str
    repository: str
    path: str
    content_sha256: str
    symbol: str | None
    symbol_kind: str | None
    start_line: int
    end_line: int
    content: str
    commit_sha: str


@dataclass(frozen=True, slots=True)
class CodeIndexResult:
    commit_sha: str
    indexed_files: int
    changed_files: int
    deleted_files: int
    indexed_chunks: int
