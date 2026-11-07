from dataclasses import asdict
from typing import Any

from mcp.server.mcpserver import MCPServer

from local_coding_copilot.bootstrap import Application, build_application
from local_coding_copilot.rag.models import AnswerMode
from local_coding_copilot.settings import api_token


def create_mcp_server(application: Application) -> MCPServer:
    server = MCPServer(name="local-coding-copilot", version="0.1.0")

    @server.tool()
    def query_documents(
        question: str,
        limit: int = 5,
        mode: AnswerMode = "grounded",
        project_id: str = "default",
    ) -> dict[str, Any]:
        """Answer a question from documents visible to the authenticated user."""
        principal = application.auth.authenticate(api_token())
        return asdict(
            application.service.query(
                question,
                limit,
                mode,
                principal=principal,
                project_id=project_id,
                transport="mcp",
            )
        )

    @server.tool()
    def query_code(
        question: str,
        limit: int = 5,
        mode: AnswerMode = "grounded",
        project_id: str = "default",
    ) -> dict[str, Any]:
        """Find project code with symbol, path and commit-aware citations."""
        principal = application.auth.authenticate(api_token())
        return asdict(
            application.code_service.query(
                question,
                limit,
                mode,
                principal=principal,
                project_id=project_id,
                transport="mcp",
            )
        )

    return server


def main() -> None:
    create_mcp_server(build_application()).run(transport="stdio")


if __name__ == "__main__":
    main()
