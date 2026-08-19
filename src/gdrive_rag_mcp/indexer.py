from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any, Protocol

from .chunking import LlamaIndexChunker
from .embeddings import Embedder
from .models import SourceDocument
from .storage import SQLiteStore


class DocumentSource(Protocol):
    def documents(self) -> Iterable[SourceDocument]: ...


class Indexer:
    def __init__(
        self,
        source: DocumentSource,
        store: SQLiteStore,
        embedder: Embedder,
        chunker: LlamaIndexChunker,
    ) -> None:
        self.source = source
        self.store = store
        self.embedder = embedder
        self.chunker = chunker

    def sync(self) -> dict[str, Any]:
        known = self.store.document_checksums()
        active_ids: set[str] = set()
        added = updated = unchanged = skipped = 0
        for document in self.source.documents():
            active_ids.add(document.id)
            if known.get(document.id) == document.checksum:
                unchanged += 1
                continue
            chunks = self.chunker.split(document.text)
            if not chunks:
                self.store.delete_document(document.id)
                skipped += 1
                continue
            embeddings = self.embedder.embed_documents(chunks)
            self.store.replace_document(document, chunks, embeddings)
            if document.id in known:
                updated += 1
            else:
                added += 1
        deleted = self.store.delete_documents_not_in(active_ids)
        summary = {
            "added": added,
            "updated": updated,
            "unchanged": unchanged,
            "deleted": deleted,
            "skipped": skipped,
            "completed_at": datetime.now(UTC).isoformat(),
        }
        self.store.set_state("last_sync", summary)
        return summary
