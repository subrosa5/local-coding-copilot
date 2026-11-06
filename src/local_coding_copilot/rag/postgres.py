from collections.abc import Sequence

import psycopg
from psycopg.rows import dict_row

from local_coding_copilot.rag.models import Chunk, Document, SearchResult

_SCHEMA = """
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS rag_documents (
    document_id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    version TEXT NOT NULL,
    content TEXT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS rag_chunks (
    chunk_id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES rag_documents ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL,
    start_line INTEGER NOT NULL,
    end_line INTEGER NOT NULL,
    content TEXT NOT NULL,
    embedding vector NOT NULL,
    UNIQUE (document_id, chunk_index)
);
"""

_SEARCH = """
WITH params AS (
    SELECT %s::vector AS embedding, websearch_to_tsquery('russian', %s) AS query
),
vector_candidates AS (
    SELECT
        chunks.chunk_id,
        1 - (chunks.embedding <=> params.embedding) AS score,
        ROW_NUMBER() OVER (ORDER BY chunks.embedding <=> params.embedding) AS rank
    FROM rag_chunks AS chunks, params
),
lexical_candidates AS (
    SELECT
        chunks.chunk_id,
        ts_rank_cd(to_tsvector('russian', chunks.content), params.query) AS score,
        ROW_NUMBER() OVER (
            ORDER BY
                ts_rank_cd(to_tsvector('russian', chunks.content), params.query) DESC,
                chunks.chunk_id
        ) AS rank
    FROM rag_chunks AS chunks, params
    WHERE to_tsvector('russian', chunks.content) @@ params.query
),
combined AS (
    SELECT
        COALESCE(vector_candidates.chunk_id, lexical_candidates.chunk_id) AS chunk_id,
        vector_candidates.score AS vector_score,
        lexical_candidates.score AS lexical_score,
        (
            COALESCE(1.0 / (60 + vector_candidates.rank), 0) +
            COALESCE(1.0 / (60 + lexical_candidates.rank), 0)
        )::float8 AS score
    FROM vector_candidates
    FULL OUTER JOIN lexical_candidates USING (chunk_id)
)
SELECT
    chunks.chunk_id,
    chunks.document_id,
    documents.source,
    documents.version,
    chunks.chunk_index,
    chunks.start_line,
    chunks.end_line,
    chunks.content,
    combined.score,
    COALESCE(combined.vector_score, 0)::float8 AS vector_score,
    COALESCE(combined.lexical_score, 0)::float8 AS lexical_score
FROM combined
JOIN rag_chunks AS chunks ON chunks.chunk_id = combined.chunk_id
JOIN rag_documents AS documents ON documents.document_id = chunks.document_id
ORDER BY combined.score DESC, chunks.chunk_id
LIMIT %s;
"""


class PostgresDocumentRepository:
    def __init__(self, dsn: str) -> None:
        self._dsn = dsn

    def initialize(self) -> None:
        with psycopg.connect(self._dsn) as connection:
            connection.execute(_SCHEMA)

    def replace_document(
        self,
        document: Document,
        chunks: Sequence[Chunk],
        embeddings: Sequence[Sequence[float]],
    ) -> None:
        if len(chunks) != len(embeddings):
            raise ValueError("Each chunk must have exactly one embedding")

        with psycopg.connect(self._dsn) as connection, connection.cursor() as cursor:
            cursor.execute(
                "DELETE FROM rag_documents WHERE document_id = %s",
                (document.document_id,),
            )
            cursor.execute(
                """
                INSERT INTO rag_documents (document_id, source, version, content)
                VALUES (%s, %s, %s, %s)
                """,
                (
                    document.document_id,
                    document.source,
                    document.version,
                    document.content,
                ),
            )
            for chunk, embedding in zip(chunks, embeddings, strict=True):
                cursor.execute(
                    """
                    INSERT INTO rag_chunks (
                        chunk_id, document_id, chunk_index, start_line, end_line,
                        content, embedding
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s::vector)
                    """,
                    (
                        chunk.chunk_id,
                        chunk.document_id,
                        chunk.chunk_index,
                        chunk.start_line,
                        chunk.end_line,
                        chunk.content,
                        _vector_literal(embedding),
                    ),
                )

    def search(
        self, query: str, embedding: Sequence[float], limit: int
    ) -> list[SearchResult]:
        with (
            psycopg.connect(self._dsn, row_factory=dict_row) as connection,
            connection.cursor() as cursor,
        ):
            cursor.execute(_SEARCH, (_vector_literal(embedding), query, limit))
            return [
                SearchResult(
                    chunk=Chunk(
                        chunk_id=row["chunk_id"],
                        document_id=row["document_id"],
                        source=row["source"],
                        version=row["version"],
                        chunk_index=row["chunk_index"],
                        start_line=row["start_line"],
                        end_line=row["end_line"],
                        content=row["content"],
                    ),
                    score=row["score"],
                    vector_score=row["vector_score"],
                    lexical_score=row["lexical_score"],
                )
                for row in cursor.fetchall()
            ]


def _vector_literal(embedding: Sequence[float]) -> str:
    return "[" + ",".join(str(float(value)) for value in embedding) + "]"
