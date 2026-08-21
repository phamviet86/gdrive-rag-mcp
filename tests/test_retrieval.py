from __future__ import annotations

from pathlib import Path

import pytest

from gdrive_rag_mcp.embeddings import HashingEmbedder
from gdrive_rag_mcp.models import SourceDocument
from gdrive_rag_mcp.retrieval import HybridRetriever
from gdrive_rag_mcp.storage import SQLiteStore


def add(store: SQLiteStore, embedder: HashingEmbedder, doc_id: str, text: str) -> None:
    document = SourceDocument(
        id=doc_id,
        name=f"{doc_id}.md",
        mime_type="text/markdown",
        modified_time="2026-08-19T00:00:00Z",
        checksum=doc_id,
        web_url=f"https://drive.google.com/open?id={doc_id}",
        text=text,
        parent_folder_id="test-root",
        ancestor_folder_ids=("test-root",),
    )
    store.replace_document(document, [text], embedder.embed_documents([text]))


def test_hybrid_search_ranks_relevant_text_and_cites_source(tmp_path: Path) -> None:
    embedder = HashingEmbedder(64)
    store = SQLiteStore(tmp_path / "index.db", embedder.dimensions)
    add(store, embedder, "tax", "Thuế giá trị gia tăng VAT áp dụng cho hàng hóa và dịch vụ.")
    add(store, embedder, "food", "Công thức nấu phở bò và nguyên liệu.")

    result = HybridRetriever(store, embedder, evidence_threshold=0.2).search(
        "thuế VAT", "test-root"
    )

    assert result["evidence"]["sufficient"] is True
    assert result["results"][0]["document_id"] == "tax"
    assert result["results"][0]["citation"]["url"].startswith("https://drive.google.com/")
    assert "modified_time" in result["results"][0]["citation"]


def test_evidence_gate_withholds_weak_results(tmp_path: Path) -> None:
    embedder = HashingEmbedder(32)
    store = SQLiteStore(tmp_path / "index.db", embedder.dimensions)
    add(store, embedder, "one", "unrelated cooking notes")

    result = HybridRetriever(store, embedder, evidence_threshold=1.01).search(
        "corporate tax", "test-root"
    )

    assert result["evidence"]["sufficient"] is False
    assert result["results"] == []
    assert "Abstain" in result["evidence"]["message"]


def test_keyword_signal_can_rescue_exact_term(tmp_path: Path) -> None:
    embedder = HashingEmbedder(32)
    store = SQLiteStore(tmp_path / "index.db", embedder.dimensions)
    add(store, embedder, "exact", "Circular 80/2021/TT-BTC filing deadline")
    add(store, embedder, "other", "general business planning")

    result = HybridRetriever(store, embedder, evidence_threshold=0.1).search(
        "80/2021/TT-BTC", "test-root"
    )
    candidates = result["results"] or result["candidate_results"]
    assert candidates[0]["document_id"] == "exact"


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("corporate income tax deadline", "english"),
        ("thời hạn thuế thu nhập doanh nghiệp", "vietnamese"),
        ("موعد ضريبة الشركات", "arabic"),
    ],
)
def test_unicode_hybrid_retrieval_across_multiple_scripts(
    tmp_path: Path, query: str, expected: str
) -> None:
    embedder = HashingEmbedder(128)
    store = SQLiteStore(tmp_path / "index.db", embedder.dimensions)
    add(store, embedder, "english", "Corporate income tax filing deadline and forms")
    add(store, embedder, "vietnamese", "Thời hạn khai thuế thu nhập doanh nghiệp và biểu mẫu")
    add(store, embedder, "arabic", "موعد تقديم ضريبة الشركات والنماذج المطلوبة")

    result = HybridRetriever(store, embedder, evidence_threshold=0.15).search(query, "test-root")
    candidates = result["results"] or result["candidate_results"]

    assert candidates[0]["document_id"] == expected
