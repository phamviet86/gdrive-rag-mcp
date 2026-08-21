from __future__ import annotations

from .chunking import LlamaIndexChunker
from .config import Settings
from .drive import GoogleDriveSource
from .embeddings import create_embedder
from .indexer import Indexer
from .retrieval import HybridRetriever
from .storage import SQLiteStore


class KnowledgeService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.store = SQLiteStore(
            settings.db_path,
            settings.embed_dimensions,
            settings.embedding_identity(),
        )
        self.embedder = create_embedder(settings)
        self.retriever = HybridRetriever(self.store, self.embedder, settings.evidence_threshold)

    def sync(self) -> dict[str, object]:
        self.settings.require_sync()
        source = GoogleDriveSource(self.settings)
        indexer = Indexer(
            source,
            self.store,
            self.embedder,
            LlamaIndexChunker(self.settings.chunk_size, self.settings.chunk_overlap),
        )
        page_token = self.store.get_state("drive_start_page_token")
        if not isinstance(page_token, str) or not page_token:
            return self.full_sync(source, indexer)
        batch = source.changes(page_token)
        if batch.full_rescan_required:
            return self.full_sync(source, indexer)
        summary = indexer.sync_changes(batch)
        self.store.set_state("drive_start_page_token", batch.new_start_page_token)
        return summary

    def full_sync(
        self,
        source: GoogleDriveSource | None = None,
        indexer: Indexer | None = None,
    ) -> dict[str, object]:
        self.settings.require_sync()
        source = source or GoogleDriveSource(self.settings)
        indexer = indexer or Indexer(
            source,
            self.store,
            self.embedder,
            LlamaIndexChunker(self.settings.chunk_size, self.settings.chunk_overlap),
        )
        page_token = source.start_page_token()
        summary = indexer.sync()
        summary["mode"] = "full"
        self.store.set_state("drive_start_page_token", page_token)
        return summary
