from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any, Protocol

from .chunking import LlamaIndexChunker
from .embeddings import Embedder
from .models import DriveChangeBatch, SourceDocument
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

    @staticmethod
    def _fingerprint(document: SourceDocument) -> str:
        return "\0".join(
            (
                document.checksum,
                document.owner_profile_id,
                document.business_function,
                document.para_category,
                document.relative_path,
                document.parent_folder_id,
                *document.ancestor_folder_ids,
            )
        )

    def _replace(self, document: SourceDocument) -> bool:
        chunks = self.chunker.split(document.text)
        if not chunks:
            self.store.delete_document(document.id)
            return False
        embeddings = self.embedder.embed_documents(chunks)
        self.store.replace_document(document, chunks, embeddings)
        return True

    def sync(self) -> dict[str, Any]:
        known = self.store.document_fingerprints()
        active_ids: set[str] = set()
        added = updated = unchanged = skipped = 0
        for document in self.source.documents():
            active_ids.add(document.id)
            fingerprint = self._fingerprint(document)
            if known.get(document.id) == fingerprint:
                unchanged += 1
                continue
            if not self._replace(document):
                skipped += 1
                continue
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
            "scope_skipped": int(getattr(self.source, "scope_skipped", 0)),
            "completed_at": datetime.now(UTC).isoformat(),
        }
        self.store.set_state("last_sync", summary)
        return summary

    def sync_changes(self, batch: DriveChangeBatch) -> dict[str, Any]:
        known = self.store.document_fingerprints()
        added = updated = unchanged = skipped = deleted = 0
        for document_id in batch.delete_document_ids:
            deleted += int(self.store.delete_document(document_id))
        for document in batch.changed_documents:
            if known.get(document.id) == self._fingerprint(document):
                unchanged += 1
                continue
            if not self._replace(document):
                skipped += 1
                continue
            if document.id in known:
                updated += 1
            else:
                added += 1
        summary = {
            "mode": "changes",
            "added": added,
            "updated": updated,
            "unchanged": unchanged,
            "deleted": deleted,
            "skipped": skipped,
            "scope_skipped": batch.scope_skipped,
            "completed_at": datetime.now(UTC).isoformat(),
        }
        self.store.set_state("last_sync", summary)
        return summary
