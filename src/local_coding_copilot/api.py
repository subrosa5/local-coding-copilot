import os
from typing import Literal

import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from local_coding_copilot.bootstrap import build_rag_service
from local_coding_copilot.rag import DocumentRAGService, QueryResponse


class QueryRequest(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    limit: int = Field(default=5, ge=1, le=20)
    mode: Literal["fast", "grounded"] = "grounded"


def create_app(service: DocumentRAGService) -> FastAPI:
    app = FastAPI(title="Local Coding Copilot", version="0.1.0")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/v1/query")
    def query(request: QueryRequest) -> QueryResponse:
        try:
            return service.query(request.question, request.limit, request.mode)
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    return app


def main() -> None:
    uvicorn.run(
        create_app(build_rag_service()),
        host="127.0.0.1",
        port=int(os.environ.get("PORT", "8000")),
    )


if __name__ == "__main__":
    main()
