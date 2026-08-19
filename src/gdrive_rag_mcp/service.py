from __future__ import annotations

from .chunking import LlamaIndexChunker
from .config import Settings
from .drive import GoogleDriveSource
from .embeddings import GeminiEmbedder
from .indexer import Indexer
from .retrieval import HybridRetriever
from .storage import SQLiteStore


class KnowledgeService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.store = SQLiteStore(settings.db_path, settings.embed_dimensions)
        self.embedder = GeminiEmbedder(
            settings.gemini_api_key, settings.embed_model, settings.embed_dimensions
        )
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
