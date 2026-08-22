from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import pytest

from google_drive_rag_mcp import storage
from google_drive_rag_mcp.storage import SQLiteStore


def test_connection_context_closes_after_body_error(tmp_path: Path) -> None:
    store = object.__new__(SQLiteStore)
    store.path = tmp_path / "index.db"
    store.vector_extension = False

    with pytest.raises(RuntimeError, match="operation failed"), store.connection() as connection:
        raise RuntimeError("operation failed")

    with pytest.raises(sqlite3.ProgrammingError, match="closed database"):
        connection.execute("SELECT 1")


def test_connect_closes_connection_when_setup_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    closed = False

    class FailingConnection:
        row_factory: Any = None

        def execute(self, statement: str) -> None:
            raise RuntimeError(f"setup failed: {statement}")

        def close(self) -> None:
            nonlocal closed
            closed = True

    monkeypatch.setattr(storage.sqlite3, "connect", lambda path: FailingConnection())
    store = object.__new__(SQLiteStore)
    store.path = tmp_path / "index.db"

    with pytest.raises(RuntimeError, match="setup failed"):
        store._connect()

    assert closed
