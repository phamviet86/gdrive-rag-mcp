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
    owner_profile_id: str = ""
    business_function: str = ""
    para_category: str = ""
    relative_path: str = ""
    parent_folder_id: str = ""
    ancestor_folder_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class DocumentMetadata:
    id: str
    name: str
    mime_type: str
    modified_time: str
    checksum: str
    web_url: str
    indexed_at: str
    owner_profile_id: str
    business_function: str
    para_category: str
    relative_path: str
    parent_folder_id: str
    folder_ancestry: str


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
    owner_profile_id: str
    business_function: str
    para_category: str
    relative_path: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "document_id": self.document_id,
            "document_name": self.document_name,
            "text": self.text,
            "score": round(self.score, 4),
            "scope": {
                "owner_profile_id": self.owner_profile_id,
                "business_function": self.business_function,
                "para_category": self.para_category,
            },
            "citation": {
                "url": self.web_url,
                "relative_path": self.relative_path,
                "modified_time": self.modified_time,
                "indexed_at": self.indexed_at,
                "chunk_position": self.position,
            },
        }


@dataclass(frozen=True, slots=True)
class DriveChangeBatch:
    changed_documents: tuple[SourceDocument, ...]
    delete_document_ids: frozenset[str]
    new_start_page_token: str
    full_rescan_required: bool = False
    scope_skipped: int = 0
