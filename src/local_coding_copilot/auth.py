import hashlib
import secrets
from dataclasses import dataclass
from typing import Literal

import psycopg
from psycopg.rows import dict_row

Role = Literal["admin", "viewer"]


class AuthenticationError(PermissionError):
    pass


class AuthorizationError(PermissionError):
    pass


@dataclass(frozen=True, slots=True)
class Principal:
    user_id: str
    role: Role
    project_ids: frozenset[str]


class PostgresAuthService:
    def __init__(self, dsn: str) -> None:
        self._dsn = dsn

    def create_user(self, user_id: str, role: Role, project_ids: frozenset[str]) -> str:
        if role not in {"admin", "viewer"}:
            raise ValueError("Role must be admin or viewer")
        if not user_id.strip() or not project_ids:
            raise ValueError("User and at least one project are required")

        token = secrets.token_urlsafe(32)
        with psycopg.connect(self._dsn) as connection, connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO app_users (user_id, role) VALUES (%s, %s) "
                "ON CONFLICT (user_id) DO UPDATE SET role = EXCLUDED.role",
                (user_id, role),
            )
            cursor.execute(
                "INSERT INTO api_tokens (token_hash, user_id) VALUES (%s, %s)",
                (_hash_token(token), user_id),
            )
            for project_id in project_ids:
                cursor.execute(
                    "INSERT INTO projects (project_id) VALUES (%s) "
                    "ON CONFLICT DO NOTHING",
                    (project_id,),
                )
                cursor.execute(
                    "INSERT INTO project_members (user_id, project_id) "
                    "VALUES (%s, %s) ON CONFLICT DO NOTHING",
                    (user_id, project_id),
                )
        return token

    def authenticate(self, token: str) -> Principal:
        if not token:
            raise AuthenticationError("Missing API token")
        with (
            psycopg.connect(self._dsn, row_factory=dict_row) as connection,
            connection.cursor() as cursor,
        ):
            row = cursor.execute(
                """
                SELECT users.user_id, users.role
                FROM api_tokens
                JOIN app_users AS users ON users.user_id = api_tokens.user_id
                WHERE token_hash = %s
                """,
                (_hash_token(token),),
            ).fetchone()
            if row is None:
                raise AuthenticationError("Invalid API token")
            projects = cursor.execute(
                "SELECT project_id FROM project_members WHERE user_id = %s",
                (row["user_id"],),
            ).fetchall()
        return Principal(
            user_id=row["user_id"],
            role=row["role"],
            project_ids=frozenset(project["project_id"] for project in projects),
        )


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
