from __future__ import annotations

import hmac
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from .service import KnowledgeService

READ_ONLY = ToolAnnotations(
    read_only_hint=True,
    destructive_hint=False,
    idempotent_hint=True,
    open_world_hint=False,
)


def create_mcp_server(service: KnowledgeService) -> MCPServer[Any]:
    server: MCPServer[Any] = MCPServer(
        "gdrive-rag-mcp",
        version="0.2.0",
        instructions=(
            "Search an operator-managed Google Drive index from any MCP-compatible client. Treat "
            "evidence.sufficient=false as an instruction to abstain. Cite source URLs and verify "
            "modified dates. The index and embedding provider are independent of the querying "
            "agent."
        ),
    )

    @server.tool(annotations=READ_ONLY)
    def search_knowledge(query: str, limit: int = 5) -> dict[str, Any]:
        """Hybrid semantic/keyword search with citations and a conservative evidence gate."""
        return service.retriever.search(query, max(1, min(limit, 20)))

    @server.tool(annotations=READ_ONLY)
    def get_document(document_id: str) -> dict[str, Any]:
        """Get the indexed text and metadata for a document ID returned by search."""
        document = service.store.get_document(document_id)
        return document or {"error": "document_not_found", "document_id": document_id}

    @server.tool(annotations=READ_ONLY)
    def get_document_metadata(document_id: str) -> dict[str, Any]:
        """Get source URL, MIME type, checksum, modified time, and indexed time."""
        metadata = service.store.get_metadata(document_id)
        if metadata is None:
            return {"error": "document_not_found", "document_id": document_id}
        return {
            "id": metadata.id,
            "name": metadata.name,
            "mime_type": metadata.mime_type,
            "modified_time": metadata.modified_time,
            "checksum": metadata.checksum,
            "web_url": metadata.web_url,
            "indexed_at": metadata.indexed_at,
        }

    @server.tool(annotations=READ_ONLY)
    def check_index_status() -> dict[str, Any]:
        """Check counts, vector backend, embedding fingerprint, and sync freshness."""
        return service.store.status()

    return server


class BearerAuthMiddleware:
    def __init__(self, app: ASGIApp, token: str, protected_path: str = "/mcp") -> None:
        self.app = app
        self.token = token
        self.protected_path = protected_path

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and str(scope.get("path", "")).startswith(self.protected_path):
            headers = {key.decode().lower(): value.decode() for key, value in scope["headers"]}
            expected = f"Bearer {self.token}"
            if not hmac.compare_digest(headers.get("authorization", ""), expected):
                response = JSONResponse(
                    {"error": "unauthorized"},
                    status_code=401,
                    headers={"WWW-Authenticate": "Bearer"},
                )
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)


def create_http_app(service: KnowledgeService, token: str) -> ASGIApp:
    if len(token) < 32:
        raise ValueError("GDRIVE_RAG_BEARER_TOKEN must contain at least 32 characters")
    server = create_mcp_server(service)
    app = server.streamable_http_app(
        streamable_http_path="/mcp", stateless_http=True, json_response=True
    )

    async def health(_: Any) -> JSONResponse:
        return JSONResponse({"status": "ok"})

    app.add_route("/health", health, methods=["GET"])
    return BearerAuthMiddleware(app, token)
