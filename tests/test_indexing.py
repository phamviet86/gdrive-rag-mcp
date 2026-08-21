from __future__ import annotations

from pathlib import Path

from google_drive_rag_mcp.embeddings import HashingEmbedder
from google_drive_rag_mcp.indexer import Indexer
from google_drive_rag_mcp.models import DriveChangeBatch, SourceDocument
from google_drive_rag_mcp.storage import SQLiteStore


class FakeSource:
    def __init__(self, documents: list[SourceDocument]) -> None:
        self.items = documents

    def documents(self) -> list[SourceDocument]:
        return self.items


class OneChunk:
    def split(self, text: str) -> list[str]:
        return [text] if text.strip() else []


def document(doc_id: str, checksum: str, text: str) -> SourceDocument:
    return SourceDocument(
        id=doc_id,
        name=f"{doc_id}.txt",
        mime_type="text/plain",
        modified_time="2026-08-19T00:00:00Z",
        checksum=checksum,
        web_url=f"https://drive.google.com/open?id={doc_id}",
        text=text,
        parent_folder_id="test-root",
        ancestor_folder_ids=("test-root",),
    )


def test_incremental_add_update_and_delete(tmp_path: Path) -> None:
    embedder = HashingEmbedder(32)
    store = SQLiteStore(tmp_path / "index.db", embedder.dimensions)
    source = FakeSource([document("a", "v1", "old tax rule"), document("b", "v1", "keep")])
    indexer = Indexer(source, store, embedder, OneChunk())  # type: ignore[arg-type]

    assert indexer.sync() | {"completed_at": "ignored"} == {
        "added": 2,
        "updated": 0,
        "unchanged": 0,
        "deleted": 0,
        "skipped": 0,
        "completed_at": "ignored",
    }

    source.items = [document("a", "v2", "new tax rule")]
    result = indexer.sync()
    assert result["updated"] == 1
    assert result["deleted"] == 1
    assert result["added"] == 0
    assert store.get_document("b") is None
    assert store.get_document("a")["text"] == "new tax rule"  # type: ignore[index]

    result = indexer.sync()
    assert result["unchanged"] == 1
    assert result["updated"] == 0

    source.items = [document("a", "v3", "")]
    result = indexer.sync()
    assert result["skipped"] == 1
    assert store.get_document("a") is None


def test_status_records_sync_freshness(tmp_path: Path) -> None:
    embedder = HashingEmbedder(16)
    store = SQLiteStore(tmp_path / "index.db", embedder.dimensions)
    Indexer(FakeSource([]), store, embedder, OneChunk()).sync()  # type: ignore[arg-type]
    status = store.status()
    assert status["last_sync"] is not None
    assert status["documents"] == 0


def test_change_batch_updates_and_deletes_without_full_scan(tmp_path: Path) -> None:
    embedder = HashingEmbedder(32)
    store = SQLiteStore(tmp_path / "index.db", embedder.dimensions)
    indexer = Indexer(FakeSource([]), store, embedder, OneChunk())  # type: ignore[arg-type]
    store.replace_document(
        document("delete-me", "v1", "old"), ["old"], embedder.embed_documents(["old"])
    )

    result = indexer.sync_changes(
        DriveChangeBatch(
            changed_documents=(document("new", "v1", "new policy"),),
            delete_document_ids=frozenset({"delete-me"}),
            new_start_page_token="next-token",
        )
    )

    assert result["mode"] == "changes"
    assert result["added"] == 1
    assert result["deleted"] == 1
    assert store.get_document("delete-me") is None
    assert store.get_document("new") is not None
