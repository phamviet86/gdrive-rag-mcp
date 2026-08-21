from __future__ import annotations

from types import SimpleNamespace

import pytest

from gdrive_rag_mcp.service import KnowledgeService


def test_sync_forces_full_reconciliation_when_drive_root_changes() -> None:
    service = object.__new__(KnowledgeService)
    service.settings = SimpleNamespace(folder_id="new-root", require_sync=lambda: None)
    service.store = SimpleNamespace(get_state=lambda key: "old-root")
    service.full_sync = lambda: {"mode": "full"}  # type: ignore[method-assign]

    assert service.sync() == {"mode": "full"}


def test_serve_readiness_rejects_a_different_indexed_root() -> None:
    service = object.__new__(KnowledgeService)
    service.settings = SimpleNamespace(folder_id="configured-root")
    service.store = SimpleNamespace(get_state=lambda key: "indexed-root")

    with pytest.raises(ValueError, match="sync --full"):
        service.require_index_ready()
