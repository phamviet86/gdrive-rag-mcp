from __future__ import annotations

import sqlite3
from pathlib import Path

from google_drive_rag_mcp.embeddings import HashingEmbedder
from google_drive_rag_mcp.models import SourceDocument
from google_drive_rag_mcp.retrieval import HybridRetriever
from google_drive_rag_mcp.storage import SQLiteStore


def add_scoped(
    store: SQLiteStore,
    embedder: HashingEmbedder,
    document_id: str,
    text: str,
    ancestor_folder_ids: tuple[str, ...],
) -> None:
    document = SourceDocument(
        id=document_id,
        name=f"{document_id}.md",
        mime_type="text/markdown",
        modified_time="2026-08-21T00:00:00Z",
        checksum=f"checksum-{document_id}",
        web_url=f"https://drive.google.com/open?id={document_id}",
        text=text,
        relative_path=f"scope/{document_id}.md",
        parent_folder_id=ancestor_folder_ids[-1],
        ancestor_folder_ids=ancestor_folder_ids,
    )
    store.replace_document(document, [text], embedder.embed_documents([text]))


def test_file_id_scopes_keyword_and_vector_search_to_one_document(tmp_path: Path) -> None:
    embedder = HashingEmbedder(64)
    store = SQLiteStore(tmp_path / "index.db", embedder.dimensions)
    add_scoped(
        store,
        embedder,
        "finance-secret",
        "confidential payroll token",
        ("root", "finance-profile", "finance-hr"),
    )
    add_scoped(
        store,
        embedder,
        "shared-policy",
        "public payroll policy",
        ("root", "shared-profile", "shared-hr"),
    )
    result = HybridRetriever(store, embedder, evidence_threshold=0.0).search(
        "confidential payroll token", "shared-policy"
    )
    candidates = result["results"] or result["candidate_results"]

    assert {item["file_id"] for item in candidates} == {"shared-policy"}


def test_folder_id_scopes_to_all_descendants(tmp_path: Path) -> None:
    embedder = HashingEmbedder(32)
    store = SQLiteStore(tmp_path / "index.db", embedder.dimensions)
    add_scoped(store, embedder, "hr", "quarterly policy", ("root", "profile-a", "profile-a-hr"))
    add_scoped(store, embedder, "sales", "quarterly policy", ("root", "profile-a", "sales"))
    add_scoped(store, embedder, "other", "quarterly policy", ("root", "profile-b", "profile-b-hr"))
    retriever = HybridRetriever(store, embedder, evidence_threshold=0.0)

    root_results = retriever.search("quarterly policy", "root")["results"]
    profile_results = retriever.search("quarterly policy", "profile-a")["results"]
    hr_results = retriever.search("quarterly policy", "profile-a-hr")["results"]
    unknown = retriever.search("quarterly policy", "unknown-id")["results"]

    assert {item["file_id"] for item in root_results} == {"hr", "sales", "other"}
    assert {item["file_id"] for item in profile_results} == {"hr", "sales"}
    assert {item["file_id"] for item in hr_results} == {"hr"}
    assert unknown == []


def test_legacy_database_is_migrated_with_folder_ancestry(tmp_path: Path) -> None:
    path = tmp_path / "legacy.db"
    with sqlite3.connect(path) as db:
        db.execute(
            """CREATE TABLE documents(
                id TEXT PRIMARY KEY,name TEXT,mime_type TEXT,modified_time TEXT,
                checksum TEXT,web_url TEXT,indexed_at TEXT
            )"""
        )
    SQLiteStore(path, 8)
    with sqlite3.connect(path) as db:
        columns = {row[1] for row in db.execute("PRAGMA table_info(documents)")}
    assert {
        "relative_path",
        "parent_folder_id",
        "folder_ancestry",
    } <= columns
    with sqlite3.connect(path) as db:
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master")}
    assert "document_folder_ancestors" in tables
