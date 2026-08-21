from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from . import __version__
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
        version=__version__,
        instructions=(
            "Search an operator-managed Google Drive index from any MCP-compatible client. Treat "
            "evidence.sufficient=false as an instruction to abstain. Cite source URLs and verify "
            "modified dates. The index and embedding provider are independent of the querying "
            "agent. Pass a Drive folder ID to search its complete subtree, or a file ID to search "
            "only that indexed file."
        ),
    )

    @server.tool(annotations=READ_ONLY)
    def search_knowledge(
        query: str,
        scope_id: str,
        limit: int = 5,
    ) -> dict[str, Any]:
        """Search one indexed file ID or one folder ID and all of its descendants."""
        return service.retriever.search(
            query,
            scope_id,
            max(1, min(limit, 20)),
        )

    @server.tool(annotations=READ_ONLY)
    def get_document(file_id: str) -> dict[str, Any]:
        """Resolve an indexed document ID for a current read through Google Workspace."""
        metadata = service.store.get_metadata(file_id)
        if metadata is None:
            return {"error": "file_not_indexed", "file_id": file_id}
        return {
            "file_id": metadata.id,
            "name": metadata.name,
            "web_url": metadata.web_url,
            "modified_time": metadata.modified_time,
            "indexed_at": metadata.indexed_at,
            "relative_path": metadata.relative_path,
            "ancestor_folder_ids": json.loads(metadata.folder_ancestry),
            "authority": "google_drive",
            "cached_full_text_returned": False,
            "instruction": (
                "Read this file_id with the client's Google Workspace tool. "
                "Google Drive, not the local index, is the authoritative full document."
            ),
        }

    @server.tool(annotations=READ_ONLY)
    def get_document_metadata(file_id: str) -> dict[str, Any]:
        """Get source URL, MIME type, checksum, modified time, and indexed time."""
        metadata = service.store.get_metadata(file_id)
        if metadata is None:
            return {"error": "file_not_indexed", "file_id": file_id}
        return {
            "id": metadata.id,
            "name": metadata.name,
            "mime_type": metadata.mime_type,
            "modified_time": metadata.modified_time,
            "checksum": metadata.checksum,
            "web_url": metadata.web_url,
            "indexed_at": metadata.indexed_at,
            "relative_path": metadata.relative_path,
            "ancestor_folder_ids": json.loads(metadata.folder_ancestry),
        }

    @server.tool(annotations=READ_ONLY)
    def check_index_status() -> dict[str, Any]:
        """Check counts, vector backend, embedding fingerprint, and sync freshness."""
        return service.store.status()

    return server


class BearerAuthMiddleware:
    def __init__(
        self,
        app: ASGIApp,
        bearer_token: str,
        protected_path: str = "/mcp",
    ) -> None:
        self.app = app
        if len(bearer_token) < 32:
            raise ValueError("GDRIVE_RAG_BEARER_TOKEN must contain at least 32 characters")
        self.token_digest = hashlib.sha256(bearer_token.encode()).digest()
        self.protected_path = protected_path

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and str(scope.get("path", "")).startswith(self.protected_path):
            headers = {key.decode().lower(): value.decode() for key, value in scope["headers"]}
            authorization = headers.get("authorization", "")
            bearer = authorization[7:] if authorization.startswith("Bearer ") else ""
            candidate = hashlib.sha256(bearer.encode()).digest() if bearer else b""
            if not hmac.compare_digest(candidate, self.token_digest):
                response = JSONResponse(
                    {"error": "unauthorized"},
                    status_code=401,
                    headers={"WWW-Authenticate": "Bearer"},
                )
                await response(scope, receive, send)
                return
            await self.app(scope, receive, send)
            return
        await self.app(scope, receive, send)


def create_http_app(service: KnowledgeService, bearer_token: str) -> ASGIApp:
    server = create_mcp_server(service)
    app = server.streamable_http_app(
        streamable_http_path="/mcp", stateless_http=True, json_response=True
    )

    async def health(_: Any) -> JSONResponse:
        return JSONResponse({"status": "ok"})

    app.add_route("/health", health, methods=["GET"])
    return BearerAuthMiddleware(app, bearer_token)
