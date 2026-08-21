from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from gdrive_rag_mcp.access import AccessPolicy, AccessScope
from gdrive_rag_mcp.embeddings import HashingEmbedder
from gdrive_rag_mcp.models import SourceDocument
from gdrive_rag_mcp.retrieval import HybridRetriever
from gdrive_rag_mcp.storage import SQLiteStore


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


def test_search_filters_before_keyword_and_vector_scoring(tmp_path: Path) -> None:
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
    scope = AccessScope.create("member", ["shared-profile"])

    result = HybridRetriever(store, embedder, evidence_threshold=0.0).search(
        "confidential payroll token", "root", scope=scope
    )
    candidates = result["results"] or result["candidate_results"]

    assert {item["document_id"] for item in candidates} == {"shared-policy"}
    assert store.get_document("finance-secret", scope) is None
    assert store.get_metadata("finance-secret", scope) is None


def test_folder_id_scopes_to_all_descendants_and_cannot_escape_token_root(
    tmp_path: Path,
) -> None:
    embedder = HashingEmbedder(32)
    store = SQLiteStore(tmp_path / "index.db", embedder.dimensions)
    add_scoped(store, embedder, "hr", "quarterly policy", ("root", "profile-a", "hr"))
    add_scoped(store, embedder, "sales", "quarterly policy", ("root", "profile-a", "sales"))
    add_scoped(store, embedder, "other", "quarterly policy", ("root", "profile-b", "hr"))
    scope = AccessScope.create("profile-a", ["profile-a"])
    retriever = HybridRetriever(store, embedder, evidence_threshold=0.0)

    profile_results = retriever.search("quarterly policy", "profile-a", scope=scope)["results"]
    hr_results = retriever.search("quarterly policy", "hr", scope=scope)["results"]
    forbidden = retriever.search("quarterly policy", "profile-b", scope=scope)["results"]

    assert {item["document_id"] for item in profile_results} == {"hr", "sales"}
    assert {item["document_id"] for item in hr_results} == {"hr"}
    assert forbidden == []


def test_access_policy_resolves_token_env_without_storing_plaintext(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    token = "a" * 64
    monkeypatch.setenv("TOKEN_FINANCE", token)
    path = tmp_path / "access-policy.json"
    path.write_text(
        json.dumps(
            {
                "principals": [
                    {
                        "profile_id": "finance",
                        "token_env": "TOKEN_FINANCE",
                        "allowed_folder_ids": ["finance-profile-folder-id"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    policy = AccessPolicy.from_file(path)

    assert policy.authenticate(token) is not None
    assert policy.authenticate("wrong") is None
    assert token not in repr(policy.principals)


def test_legacy_database_is_migrated_with_denyable_scope_columns(tmp_path: Path) -> None:
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
        "owner_profile_id",
        "business_function",
        "para_category",
        "relative_path",
        "parent_folder_id",
        "folder_ancestry",
    } <= columns
    with sqlite3.connect(path) as db:
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master")}
    assert "document_folder_ancestors" in tables
