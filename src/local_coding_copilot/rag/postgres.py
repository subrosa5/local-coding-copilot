from collections.abc import Sequence

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from local_coding_copilot.rag.models import Chunk, Document, SearchResult

_SCHEMA = """
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS app_users (
    user_id TEXT PRIMARY KEY,
    role TEXT NOT NULL CHECK (role IN ('admin', 'viewer')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS projects (
    project_id TEXT PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS project_members (
    user_id TEXT NOT NULL REFERENCES app_users ON DELETE CASCADE,
    project_id TEXT NOT NULL REFERENCES projects ON DELETE CASCADE,
    PRIMARY KEY (user_id, project_id)
);

CREATE TABLE IF NOT EXISTS api_tokens (
    token_hash TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES app_users ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS rag_documents (
    document_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL DEFAULT 'default',
    source TEXT NOT NULL,
    version TEXT NOT NULL,
    content TEXT NOT NULL,
    embedding_fingerprint TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE rag_documents
    ADD COLUMN IF NOT EXISTS project_id TEXT NOT NULL DEFAULT 'default';

ALTER TABLE rag_documents
    ADD COLUMN IF NOT EXISTS embedding_fingerprint TEXT;

CREATE INDEX IF NOT EXISTS rag_documents_project_embedding_idx
    ON rag_documents (project_id, embedding_fingerprint);

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

CREATE TABLE IF NOT EXISTS audit_events (
    event_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    action TEXT NOT NULL,
    transport TEXT NOT NULL,
    outcome TEXT NOT NULL,
    reason TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""

_SEARCH = """
WITH params AS (
    SELECT
        %s::vector AS embedding,
        (
            SELECT to_tsquery('russian', string_agg(lexeme, ' | '))
            FROM unnest(tsvector_to_array(to_tsvector('russian', %s))) AS terms(lexeme)
        ) AS query
),
visible_chunks AS (
    SELECT chunks.*
    FROM rag_chunks AS chunks
    JOIN rag_documents AS documents
        ON documents.document_id = chunks.document_id
    JOIN project_members AS members
        ON members.project_id = documents.project_id
    WHERE members.user_id = %s AND documents.project_id = %s
),
vector_candidates AS (
    SELECT
        chunks.chunk_id,
        1 - (chunks.embedding <=> params.embedding) AS score,
        ROW_NUMBER() OVER (ORDER BY chunks.embedding <=> params.embedding) AS rank
    FROM visible_chunks AS chunks, params
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
    FROM visible_chunks AS chunks, params
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
    documents.project_id,
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
        embedding_fingerprint: str,
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
                INSERT INTO rag_documents (
                    document_id, project_id, source, version, content,
                    embedding_fingerprint
                ) VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    document.document_id,
                    document.project_id,
                    document.source,
                    document.version,
                    document.content,
                    embedding_fingerprint,
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

    def assert_embedding_fingerprint(
        self, project_id: str, embedding_fingerprint: str
    ) -> None:
        from local_coding_copilot.rag.repository import EmbeddingFingerprintMismatch

        with psycopg.connect(self._dsn) as connection:
            has_mismatch = connection.execute(
                """
                SELECT EXISTS (
                    SELECT 1 FROM rag_documents
                WHERE project_id = %s
                    AND embedding_fingerprint IS DISTINCT FROM %s
                    LIMIT 1
                )
                """,
                (project_id, embedding_fingerprint),
            ).fetchone()[0]
        if has_mismatch:
            raise EmbeddingFingerprintMismatch(
                f"Documents in project {project_id!r} use a different or unknown "
                "embedding model; re-ingest the full project before querying"
            )

    def delete_documents_except(
        self, project_id: str, document_ids: Sequence[str]
    ) -> int:
        with psycopg.connect(self._dsn) as connection:
            cursor = connection.execute(
                """
                DELETE FROM rag_documents
                WHERE project_id = %s AND NOT (document_id = ANY(%s))
                """,
                (project_id, list(document_ids)),
            )
            return cursor.rowcount

    def search(
        self,
        query: str,
        embedding: Sequence[float],
        limit: int,
        user_id: str,
        project_id: str,
    ) -> list[SearchResult]:
        with (
            psycopg.connect(self._dsn, row_factory=dict_row) as connection,
            connection.cursor() as cursor,
        ):
            cursor.execute(
                _SEARCH,
                (_vector_literal(embedding), query, user_id, project_id, limit),
            )
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
                        project_id=row["project_id"],
                    ),
                    score=row["score"],
                    vector_score=row["vector_score"],
                    lexical_score=row["lexical_score"],
                )
                for row in cursor.fetchall()
            ]

    def record_audit(
        self,
        user_id: str,
        project_id: str,
        action: str,
        transport: str,
        outcome: str,
        reason: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> None:
        with psycopg.connect(self._dsn) as connection:
            connection.execute(
                """
                INSERT INTO audit_events (
                    user_id, project_id, action, transport, outcome, reason, metadata
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    user_id,
                    project_id,
                    action,
                    transport,
                    outcome,
                    reason,
                    Jsonb(metadata or {}),
                ),
            )


def _vector_literal(embedding: Sequence[float]) -> str:
    return "[" + ",".join(str(float(value)) for value in embedding) + "]"
