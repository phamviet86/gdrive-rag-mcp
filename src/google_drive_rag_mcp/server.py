from __future__ import annotations

import json
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

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
        "google-drive-rag-mcp",
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
