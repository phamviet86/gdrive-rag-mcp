from __future__ import annotations

from llama_index.core.node_parser import SentenceSplitter


class LlamaIndexChunker:
    """Thin adapter that keeps LlamaIndex at the replaceable pipeline boundary."""

    def __init__(self, chunk_size: int = 700, chunk_overlap: int = 100) -> None:
        self.splitter = SentenceSplitter(chunk_size=chunk_size, chunk_overlap=chunk_overlap)

    def split(self, text: str) -> list[str]:
        return [part.strip() for part in self.splitter.split_text(text) if part.strip()]
