from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class SourceDocument:
    id: str
    name: str
    mime_type: str
    modified_time: str
    checksum: str
    web_url: str
    text: str


@dataclass(frozen=True, slots=True)
class DocumentMetadata:
    id: str
    name: str
    mime_type: str
    modified_time: str
    checksum: str
    web_url: str
    indexed_at: str


@dataclass(frozen=True, slots=True)
class SearchHit:
    chunk_id: int
    document_id: str
    document_name: str
    text: str
    score: float
    modified_time: str
    indexed_at: str
    web_url: str
    position: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "document_id": self.document_id,
            "document_name": self.document_name,
            "text": self.text,
            "score": round(self.score, 4),
            "citation": {
                "url": self.web_url,
                "modified_time": self.modified_time,
                "indexed_at": self.indexed_at,
                "chunk_position": self.position,
            },
        }
