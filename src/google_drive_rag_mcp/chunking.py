from __future__ import annotations

import re

from llama_index.core.node_parser import SentenceSplitter

_SENTENCE_END = re.compile(
    r"(?:(?:[.!?]+|\u2026+)(?:[\"'\u2019\u201d\u00bb)\]]+)?(?=\s|$)|"
    r"[\u3002\uff01\uff1f]+(?:[\"'\u2019\u201d\u00bb)\]]+)?)"
)


def _split_sentences(text: str) -> list[str]:
    """Split on multilingual sentence punctuation without external language data."""
    sentences: list[str] = []
    start = 0
    for match in _SENTENCE_END.finditer(text):
        sentences.append(text[start : match.end()])
        start = match.end()
    if start < len(text):
        sentences.append(text[start:])
    return sentences


class LlamaIndexChunker:
    """Thin adapter that keeps LlamaIndex at the replaceable pipeline boundary."""

    def __init__(self, chunk_size: int = 700, chunk_overlap: int = 100) -> None:
        self.splitter = SentenceSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            chunking_tokenizer_fn=_split_sentences,
        )

    def split(self, text: str) -> list[str]:
        return [part.strip() for part in self.splitter.split_text(text) if part.strip()]
