import argparse

from local_coding_copilot.auth import PostgresAuthService
from local_coding_copilot.rag.postgres import PostgresDocumentRepository
from local_coding_copilot.settings import database_dsn


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a local POC user and token")
    parser.add_argument("--user-id", required=True)
    parser.add_argument("--role", choices=("admin", "viewer"), default="viewer")
    parser.add_argument("--project-id", action="append", required=True)
    args = parser.parse_args()

    dsn = database_dsn()
    PostgresDocumentRepository(dsn).initialize()
    token = PostgresAuthService(dsn).create_user(
        user_id=args.user_id,
        role=args.role,
        project_ids=frozenset(args.project_id),
    )
    print(token)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
