import os


def database_dsn() -> str:
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        raise RuntimeError("DATABASE_URL is required")
    return dsn


def api_token() -> str:
    token = os.environ.get("COPILOT_API_TOKEN")
    if not token:
        raise RuntimeError("COPILOT_API_TOKEN is required")
    return token
