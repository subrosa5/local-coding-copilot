from dataclasses import asdict
from typing import Any

from mcp.server.mcpserver import MCPServer

from local_coding_copilot.bootstrap import build_rag_service
from local_coding_copilot.rag import DocumentRAGService


def create_mcp_server(service: DocumentRAGService) -> MCPServer:
    server = MCPServer(name="local-coding-copilot", version="0.1.0")

    @server.tool()
    def query_documents(question: str, limit: int = 5) -> dict[str, Any]:
        """Answer a question from indexed project documents with citations."""
        return asdict(service.query(question, limit))

    return server


def main() -> None:
    create_mcp_server(build_rag_service()).run(transport="stdio")


if __name__ == "__main__":
    main()
