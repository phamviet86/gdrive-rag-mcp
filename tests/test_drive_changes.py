from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from gdrive_rag_mcp.drive import FOLDER_MIME, GoogleDriveSource
from gdrive_rag_mcp.models import SourceDocument


class Request:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload

    def execute(self) -> dict[str, Any]:
        return self.payload


class Changes:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload

    def list(self, **_: Any) -> Request:
        return Request(self.payload)


class Service:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload

    def changes(self) -> Changes:
        return Changes(self.payload)


def document(document_id: str) -> SourceDocument:
    return SourceDocument(
        id=document_id,
        name="policy.md",
        mime_type="text/markdown",
        modified_time="2026-08-21T00:00:00Z",
        checksum="checksum",
        web_url=f"https://drive.google.com/open?id={document_id}",
        text="policy",
        relative_path="shared/operations/areas/policy.md",
        parent_folder_id="areas-folder",
        ancestor_folder_ids=("root", "shared", "operations", "areas-folder"),
    )


def test_changes_batch_tracks_updates_deletes_and_new_token() -> None:
    source = object.__new__(GoogleDriveSource)
    source.settings = SimpleNamespace(shared_drive_id=None)
    source.service = Service(
        {
            "changes": [
                {"fileId": "updated", "file": {"mimeType": "text/markdown"}},
                {"fileId": "deleted", "removed": True},
            ],
            "newStartPageToken": "next-token",
        }
    )
    source.document_by_id = lambda file_id: document(file_id)  # type: ignore[method-assign]

    batch = source.changes("old-token")

    assert [item.id for item in batch.changed_documents] == ["updated"]
    assert batch.delete_document_ids == frozenset({"deleted"})
    assert batch.new_start_page_token == "next-token"
    assert not batch.full_rescan_required


def test_folder_change_requests_full_reconciliation() -> None:
    source = object.__new__(GoogleDriveSource)
    source.settings = SimpleNamespace(shared_drive_id=None)
    source.service = Service(
        {
            "changes": [{"fileId": "folder", "file": {"mimeType": FOLDER_MIME}}],
            "newStartPageToken": "next-token",
        }
    )

    assert source.changes("old-token").full_rescan_required
