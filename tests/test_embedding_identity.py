from __future__ import annotations

from pathlib import Path

import pytest

from gdrive_rag_mcp.embeddings import EmbeddingIdentity, HashingEmbedder
from gdrive_rag_mcp.models import SourceDocument
from gdrive_rag_mcp.storage import ReindexRequiredError, SQLiteStore


def source_document() -> SourceDocument:
    return SourceDocument(
        id="doc",
        name="doc.txt",
        mime_type="text/plain",
        modified_time="2026-08-19T00:00:00Z",
        checksum="v1",
        web_url="https://drive.google.com/open?id=doc",
        text="example",
    )


def test_fingerprint_prevents_provider_model_and_dimension_mixing(tmp_path: Path) -> None:
    path = tmp_path / "index.db"
    first = EmbeddingIdentity("gemini", "model-a", 8, "google-gemini-api")
    SQLiteStore(path, 8, first)
    SQLiteStore(path, 8, first)

    for mismatch in (
        EmbeddingIdentity("openai-compatible", "model-a", 8, "https://example.test/v1"),
        EmbeddingIdentity("gemini", "model-b", 8, "google-gemini-api"),
        EmbeddingIdentity("gemini", "model-a", 16, "google-gemini-api"),
    ):
        with pytest.raises(ReindexRequiredError, match="does not match"):
            SQLiteStore(path, mismatch.dimensions, mismatch)


def test_nonempty_legacy_index_requires_explicit_reindex(tmp_path: Path) -> None:
    path = tmp_path / "legacy.db"
    embedder = HashingEmbedder(8)
    legacy = SQLiteStore(path, 8)
    legacy.replace_document(
        source_document(), ["legacy vector"], embedder.embed_documents(["legacy vector"])
    )

    with pytest.raises(ReindexRequiredError, match="legacy index"):
        SQLiteStore(path, 8, EmbeddingIdentity("gemini", "gemini-embedding-001", 8))


def test_empty_legacy_index_rebuilds_vector_table_for_configured_dimensions(
    tmp_path: Path,
) -> None:
    path = tmp_path / "legacy-empty.db"
    SQLiteStore(path, 8)
    identity = EmbeddingIdentity("gemini", "gemini-embedding-001", 16)

    migrated = SQLiteStore(path, 16, identity)
    embedder = HashingEmbedder(16)
    migrated.replace_document(
        source_document(), ["new vector"], embedder.embed_documents(["new vector"])
    )

    assert migrated.status()["chunks"] == 1


def test_confirmed_reset_rebinds_index_identity(tmp_path: Path) -> None:
    path = tmp_path / "index.db"
    old = EmbeddingIdentity("gemini", "old", 8, "google-gemini-api")
    new = EmbeddingIdentity("sentence-transformers", "new", 16, "local")
    store = SQLiteStore(path, 8, old)
    embedder = HashingEmbedder(8)
    store.replace_document(source_document(), ["old"], embedder.embed_documents(["old"]))

    maintenance = SQLiteStore(path, 16, new, enforce_identity=False)
    maintenance.reset_index(new)

    reopened = SQLiteStore(path, 16, new)
    assert reopened.status()["documents"] == 0
    assert reopened.status()["embedding_identity"]["fingerprint"] == new.fingerprint
