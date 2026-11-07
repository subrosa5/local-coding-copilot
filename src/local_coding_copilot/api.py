import os
from typing import Annotated, Literal

import uvicorn
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from local_coding_copilot.auth import AuthenticationError, AuthorizationError
from local_coding_copilot.bootstrap import Application, build_application
from local_coding_copilot.rag import QueryResponse
from local_coding_copilot.rate_limit import RateLimitExceeded


class QueryRequest(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    limit: int = Field(default=5, ge=1, le=20)
    mode: Literal["fast", "grounded"] = "grounded"
    project_id: str = Field(default="default", min_length=1, max_length=128)


def create_app(application: Application) -> FastAPI:
    app = FastAPI(title="Local Coding Copilot", version="0.1.0")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/v1/query")
    def query(
        request: QueryRequest,
        authorization: Annotated[str | None, Header()] = None,
    ) -> QueryResponse:
        try:
            principal = application.auth.authenticate(_bearer_token(authorization))
            return application.service.query(
                request.question,
                request.limit,
                request.mode,
                principal=principal,
                project_id=request.project_id,
                transport="http",
            )
        except AuthenticationError as error:
            raise HTTPException(
                status_code=401,
                detail=str(error),
                headers={"WWW-Authenticate": "Bearer"},
            ) from error
        except AuthorizationError as error:
            raise HTTPException(status_code=403, detail=str(error)) from error
        except RateLimitExceeded as error:
            raise HTTPException(status_code=429, detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    return app


def _bearer_token(authorization: str | None) -> str:
    if not authorization:
        raise AuthenticationError("Missing Authorization header")
    scheme, separator, token = authorization.partition(" ")
    if scheme.casefold() != "bearer" or not separator or not token.strip():
        raise AuthenticationError("Expected a Bearer API token")
    return token.strip()


def main() -> None:
    uvicorn.run(
        create_app(build_application()),
        host="127.0.0.1",
        port=int(os.environ.get("PORT", "8000")),
    )


if __name__ == "__main__":
    main()
