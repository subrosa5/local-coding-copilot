from collections.abc import Sequence

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from local_coding_copilot.code.models import CodeChunk
from local_coding_copilot.rag.models import Chunk, SearchResult

_SCHEMA = """
CREATE TABLE IF NOT EXISTS code_repositories (
    project_id TEXT NOT NULL,
    repository TEXT NOT NULL,
    commit_sha TEXT NOT NULL,
    embedding_fingerprint TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (project_id, repository)
);

ALTER TABLE code_repositories
    ADD COLUMN IF NOT EXISTS embedding_fingerprint TEXT;

CREATE TABLE IF NOT EXISTS code_chunks (
    chunk_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    repository TEXT NOT NULL,
    path TEXT NOT NULL,
    content_sha256 TEXT NOT NULL,
    symbol TEXT,
    symbol_kind TEXT,
    start_line INTEGER NOT NULL,
    end_line INTEGER NOT NULL,
    content TEXT NOT NULL,
    commit_sha TEXT NOT NULL,
    embedding vector NOT NULL,
    indexed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS code_chunks_path_idx
    ON code_chunks (project_id, repository, path);
"""

_SEARCH = """
WITH params AS (
    SELECT
        %s::vector AS embedding,
        %s::text AS exact_query,
        (
            SELECT to_tsquery('russian', string_agg(lexeme, ' | '))
            FROM unnest(tsvector_to_array(to_tsvector('russian', %s))) AS terms(lexeme)
        ) AS query
),
visible_chunks AS (
    SELECT chunks.*
    FROM code_chunks AS chunks
    JOIN project_members AS members
        ON members.project_id = chunks.project_id
    WHERE members.user_id = %s AND chunks.project_id = %s
),
vector_candidates AS (
    SELECT
        chunks.chunk_id,
        1 - (chunks.embedding <=> params.embedding) AS score,
        ROW_NUMBER() OVER (ORDER BY chunks.embedding <=> params.embedding) AS rank
    FROM visible_chunks AS chunks, params
),
lexical_scored AS (
    SELECT
        chunks.chunk_id,
        (
            COALESCE(
                ts_rank_cd(to_tsvector('russian', chunks.content), params.query),
                0
            ) +
            CASE
                WHEN chunks.symbol IS NOT NULL
                    AND lower(chunks.symbol) = lower(params.exact_query)
                THEN 10.0 ELSE 0.0
            END +
            CASE
                WHEN position(lower(params.exact_query) in lower(chunks.path)) > 0
                THEN 2.0 ELSE 0.0
            END +
            CASE
                WHEN chunks.symbol IS NOT NULL
                    AND position(lower(params.exact_query) in lower(chunks.symbol)) > 0
                THEN 3.0 ELSE 0.0
            END +
            CASE
                WHEN position(lower(params.exact_query) in lower(chunks.content)) > 0
                THEN 1.0 ELSE 0.0
            END
        )::float8 AS score
    FROM visible_chunks AS chunks, params
),
lexical_candidates AS (
    SELECT
        chunk_id,
        score,
        ROW_NUMBER() OVER (ORDER BY score DESC, chunk_id) AS rank
    FROM lexical_scored
    WHERE score > 0
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
    chunks.path AS document_id,
    chunks.path AS source,
    chunks.commit_sha AS version,
    chunks.project_id,
    chunks.repository,
    chunks.symbol,
    chunks.symbol_kind,
    chunks.commit_sha,
    chunks.start_line,
    chunks.end_line,
    chunks.content,
    combined.score,
    COALESCE(combined.vector_score, 0)::float8 AS vector_score,
    COALESCE(combined.lexical_score, 0)::float8 AS lexical_score
FROM combined
JOIN code_chunks AS chunks ON chunks.chunk_id = combined.chunk_id
ORDER BY combined.score DESC, chunks.chunk_id
LIMIT %s;
"""


class PostgresCodeRepository:
    def __init__(self, dsn: str) -> None:
        self._dsn = dsn

    def initialize(self) -> None:
        with psycopg.connect(self._dsn) as connection:
            connection.execute(_SCHEMA)

    def indexed_files(self, project_id: str, repository: str) -> dict[str, str]:
        with (
            psycopg.connect(self._dsn, row_factory=dict_row) as connection,
            connection.cursor() as cursor,
        ):
            rows = cursor.execute(
                """
                SELECT DISTINCT ON (path) path, content_sha256
                FROM code_chunks
                WHERE project_id = %s AND repository = %s
                ORDER BY path, chunk_id
                """,
                (project_id, repository),
            ).fetchall()
        return {row["path"]: row["content_sha256"] for row in rows}

    def current_commit(self, project_id: str, repository: str) -> str | None:
        with psycopg.connect(self._dsn) as connection:
            row = connection.execute(
                """
                SELECT commit_sha FROM code_repositories
                WHERE project_id = %s AND repository = %s
                """,
                (project_id, repository),
            ).fetchone()
        return row[0] if row else None

    def current_embedding_fingerprint(
        self, project_id: str, repository: str
    ) -> str | None:
        with psycopg.connect(self._dsn) as connection:
            row = connection.execute(
                """
                SELECT embedding_fingerprint FROM code_repositories
                WHERE project_id = %s AND repository = %s
                """,
                (project_id, repository),
            ).fetchone()
        return row[0] if row else None

    def assert_embedding_fingerprint(
        self, project_id: str, embedding_fingerprint: str
    ) -> None:
        from local_coding_copilot.rag.repository import EmbeddingFingerprintMismatch

        with psycopg.connect(self._dsn) as connection:
            has_mismatch = connection.execute(
                """
                SELECT EXISTS (
                    SELECT 1 FROM code_repositories
                WHERE project_id = %s
                    AND embedding_fingerprint IS DISTINCT FROM %s
                    LIMIT 1
                )
                """,
                (project_id, embedding_fingerprint),
            ).fetchone()[0]
            has_unregistered = connection.execute(
                """
                SELECT EXISTS (
                    SELECT 1
                FROM code_chunks AS chunks
                LEFT JOIN code_repositories AS repositories
                    USING (project_id, repository)
                WHERE chunks.project_id = %s
                    AND repositories.project_id IS NULL
                    LIMIT 1
                )
                """,
                (project_id,),
            ).fetchone()[0]
        if has_mismatch or has_unregistered:
            raise EmbeddingFingerprintMismatch(
                f"Code index for project {project_id!r} uses a different or "
                "unknown embedding model; re-index all project repositories before "
                "querying"
            )

    def apply_changes(
        self,
        project_id: str,
        repository: str,
        commit_sha: str,
        chunks: Sequence[CodeChunk],
        embeddings: Sequence[Sequence[float]],
        embedding_fingerprint: str,
        changed_paths: Sequence[str],
        deleted_paths: Sequence[str],
    ) -> None:
        if len(chunks) != len(embeddings):
            raise ValueError("Each code chunk must have exactly one embedding")

        with psycopg.connect(self._dsn) as connection, connection.cursor() as cursor:
            paths = list(dict.fromkeys([*changed_paths, *deleted_paths]))
            if paths:
                cursor.execute(
                    """
                    DELETE FROM code_chunks
                    WHERE project_id = %s AND repository = %s AND path = ANY(%s)
                    """,
                    (project_id, repository, paths),
                )
            for chunk, embedding in zip(chunks, embeddings, strict=True):
                cursor.execute(
                    """
                    INSERT INTO code_chunks (
                        chunk_id, project_id, repository, path, content_sha256,
                        symbol, symbol_kind, start_line, end_line, content,
                        commit_sha, embedding
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::vector
                    )
                    """,
                    (
                        chunk.chunk_id,
                        chunk.project_id,
                        chunk.repository,
                        chunk.path,
                        chunk.content_sha256,
                        chunk.symbol,
                        chunk.symbol_kind,
                        chunk.start_line,
                        chunk.end_line,
                        chunk.content,
                        chunk.commit_sha,
                        _vector_literal(embedding),
                    ),
                )
            cursor.execute(
                """
                UPDATE code_chunks SET commit_sha = %s, indexed_at = now()
                WHERE project_id = %s AND repository = %s
                """,
                (commit_sha, project_id, repository),
            )
            cursor.execute(
                """
                INSERT INTO code_repositories (
                    project_id, repository, commit_sha, embedding_fingerprint
                ) VALUES (%s, %s, %s, %s)
                ON CONFLICT (project_id, repository) DO UPDATE
                SET commit_sha = EXCLUDED.commit_sha,
                    embedding_fingerprint = EXCLUDED.embedding_fingerprint,
                    updated_at = now()
                """,
                (project_id, repository, commit_sha, embedding_fingerprint),
            )

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
                (_vector_literal(embedding), query, query, user_id, project_id, limit),
            )
            return [
                SearchResult(
                    chunk=Chunk(
                        chunk_id=row["chunk_id"],
                        document_id=row["document_id"],
                        source=row["source"],
                        version=row["version"],
                        chunk_index=0,
                        start_line=row["start_line"],
                        end_line=row["end_line"],
                        content=row["content"],
                        project_id=row["project_id"],
                        repository=row["repository"],
                        symbol=row["symbol"],
                        symbol_kind=row["symbol_kind"],
                        commit_sha=row["commit_sha"],
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
