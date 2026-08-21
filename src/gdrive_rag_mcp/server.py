from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from . import __version__
from .access import (
    AccessPolicy,
    AccessScope,
    current_scope,
    reset_current_scope,
    set_current_scope,
)
from .service import KnowledgeService

READ_ONLY = ToolAnnotations(
    read_only_hint=True,
    destructive_hint=False,
    idempotent_hint=True,
    open_world_hint=False,
)


def create_mcp_server(
    service: KnowledgeService, default_scope: AccessScope | None = None
) -> MCPServer[Any]:
    server: MCPServer[Any] = MCPServer(
        "gdrive-rag-mcp",
        version=__version__,
        instructions=(
            "Search an operator-managed Google Drive index from any MCP-compatible client. Treat "
            "evidence.sufficient=false as an instruction to abstain. Cite source URLs and verify "
            "modified dates. The index and embedding provider are independent of the querying "
            "agent."
        ),
    )

    @server.tool(annotations=READ_ONLY)
    def search_knowledge(
        query: str,
        limit: int = 5,
        owner_profile_id: str = "",
        business_function: str = "",
        para_category: str = "",
    ) -> dict[str, Any]:
        """Hybrid semantic/keyword search with citations and a conservative evidence gate."""
        return service.retriever.search(
            query,
            max(1, min(limit, 20)),
            current_scope(default_scope),
            owner_profile_id,
            business_function,
            para_category,
        )

    @server.tool(annotations=READ_ONLY)
    def get_document(document_id: str) -> dict[str, Any]:
        """Resolve an authorized document ID for a current read through Google Workspace."""
        metadata = service.store.get_metadata(document_id, current_scope(default_scope))
        if metadata is None:
            return {"error": "document_not_found_or_forbidden", "document_id": document_id}
        return {
            "document_id": metadata.id,
            "name": metadata.name,
            "web_url": metadata.web_url,
            "modified_time": metadata.modified_time,
            "indexed_at": metadata.indexed_at,
            "relative_path": metadata.relative_path,
            "scope": {
                "owner_profile_id": metadata.owner_profile_id,
                "business_function": metadata.business_function,
                "para_category": metadata.para_category,
            },
            "authority": "google_drive",
            "cached_full_text_returned": False,
            "instruction": (
                "Read this document_id with the profile's authorized Google Workspace tool. "
                "Google Drive, not the local index, is the authoritative full document."
            ),
        }

    @server.tool(annotations=READ_ONLY)
    def get_document_metadata(document_id: str) -> dict[str, Any]:
        """Get source URL, MIME type, checksum, modified time, and indexed time."""
        metadata = service.store.get_metadata(document_id, current_scope(default_scope))
        if metadata is None:
            return {"error": "document_not_found_or_forbidden", "document_id": document_id}
        return {
            "id": metadata.id,
            "name": metadata.name,
            "mime_type": metadata.mime_type,
            "modified_time": metadata.modified_time,
            "checksum": metadata.checksum,
            "web_url": metadata.web_url,
            "indexed_at": metadata.indexed_at,
            "owner_profile_id": metadata.owner_profile_id,
            "business_function": metadata.business_function,
            "para_category": metadata.para_category,
            "relative_path": metadata.relative_path,
        }

    @server.tool(annotations=READ_ONLY)
    def check_index_status() -> dict[str, Any]:
        """Check counts, vector backend, embedding fingerprint, and sync freshness."""
        return service.store.status(current_scope(default_scope))

    return server


class BearerAuthMiddleware:
    def __init__(
        self,
        app: ASGIApp,
        policy: AccessPolicy | str,
        protected_path: str = "/mcp",
    ) -> None:
        self.app = app
        self.policy = (
            policy
            if isinstance(policy, AccessPolicy)
            else AccessPolicy.from_single_token(policy, AccessScope.create("legacy-http", ["*"]))
        )
        self.protected_path = protected_path

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and str(scope.get("path", "")).startswith(self.protected_path):
            headers = {key.decode().lower(): value.decode() for key, value in scope["headers"]}
            authorization = headers.get("authorization", "")
            bearer = authorization[7:] if authorization.startswith("Bearer ") else ""
            caller_scope = self.policy.authenticate(bearer) if bearer else None
            if caller_scope is None:
                response = JSONResponse(
                    {"error": "unauthorized"},
                    status_code=401,
                    headers={"WWW-Authenticate": "Bearer"},
                )
                await response(scope, receive, send)
                return
            context_token = set_current_scope(caller_scope)
            try:
                await self.app(scope, receive, send)
            finally:
                reset_current_scope(context_token)
            return
        await self.app(scope, receive, send)


def create_http_app(service: KnowledgeService, policy: AccessPolicy | str) -> ASGIApp:
    if isinstance(policy, str) and len(policy) < 32:
        raise ValueError("GDRIVE_RAG_BEARER_TOKEN must contain at least 32 characters")
    server = create_mcp_server(service)
    app = server.streamable_http_app(
        streamable_http_path="/mcp", stateless_http=True, json_response=True
    )

    async def health(_: Any) -> JSONResponse:
        return JSONResponse({"status": "ok"})

    app.add_route("/health", health, methods=["GET"])
    return BearerAuthMiddleware(app, policy)
