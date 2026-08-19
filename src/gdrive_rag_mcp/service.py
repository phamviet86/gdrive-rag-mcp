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
        indexer = Indexer(
            GoogleDriveSource(self.settings),
            self.store,
            self.embedder,
            LlamaIndexChunker(self.settings.chunk_size, self.settings.chunk_overlap),
        )
        return indexer.sync()
