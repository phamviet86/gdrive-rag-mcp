from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from gdrive_rag_mcp.access import AccessPolicy, AccessScope, normalize_para, normalize_scope_value
from gdrive_rag_mcp.embeddings import HashingEmbedder
from gdrive_rag_mcp.models import SourceDocument
from gdrive_rag_mcp.retrieval import HybridRetriever
from gdrive_rag_mcp.storage import SQLiteStore


def add_scoped(
    store: SQLiteStore,
    embedder: HashingEmbedder,
    document_id: str,
    text: str,
    owner: str,
    business_function: str,
    para_category: str = "areas",
) -> None:
    document = SourceDocument(
        id=document_id,
        name=f"{document_id}.md",
        mime_type="text/markdown",
        modified_time="2026-08-21T00:00:00Z",
        checksum=f"checksum-{document_id}",
        web_url=f"https://drive.google.com/open?id={document_id}",
        text=text,
        owner_profile_id=owner,
        business_function=business_function,
        para_category=para_category,
        relative_path=f"{owner}/{business_function}/{para_category}/{document_id}.md",
        parent_folder_id=f"folder-{document_id}",
    )
    store.replace_document(document, [text], embedder.embed_documents([text]))


def test_scope_identifiers_follow_ordered_folder_names() -> None:
    assert normalize_scope_value("01-Orchestrator") == "orchestrator"
    assert normalize_scope_value("02 Finance & Accounting") == "finance-accounting"
    assert normalize_para("03-Resource") == "resources"


def test_search_filters_before_keyword_and_vector_scoring(tmp_path: Path) -> None:
    embedder = HashingEmbedder(64)
    store = SQLiteStore(tmp_path / "index.db", embedder.dimensions)
    add_scoped(store, embedder, "finance-secret", "confidential payroll token", "finance", "hr")
    add_scoped(store, embedder, "shared-policy", "public payroll policy", "shared", "hr")
    scope = AccessScope.create("member", ["self", "shared"], ["hr"])

    result = HybridRetriever(store, embedder, evidence_threshold=0.0).search(
        "confidential payroll token", scope=scope
    )
    candidates = result["results"] or result["candidate_results"]

    assert {item["document_id"] for item in candidates} == {"shared-policy"}
    assert store.get_document("finance-secret", scope) is None
    assert store.get_metadata("finance-secret", scope) is None


def test_explicit_filter_must_be_inside_authenticated_scope(tmp_path: Path) -> None:
    embedder = HashingEmbedder(32)
    store = SQLiteStore(tmp_path / "index.db", embedder.dimensions)
    scope = AccessScope.create("finance", ["self", "shared"], ["finance"])

    with pytest.raises(PermissionError, match="outside"):
        HybridRetriever(store, embedder).search("query", scope=scope, business_function="legal")


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
                        "owner_profile_ids": ["self", "shared"],
                        "business_functions": ["finance"],
                        "para_categories": ["projects", "areas"],
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
    } <= columns
