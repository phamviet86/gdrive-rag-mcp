from __future__ import annotations

from typing import Any

from .access import AccessScope
from .embeddings import Embedder
from .storage import SQLiteStore


class HybridRetriever:
    def __init__(
        self,
        store: SQLiteStore,
        embedder: Embedder,
        evidence_threshold: float = 0.35,
        vector_weight: float = 0.65,
    ) -> None:
        self.store = store
        self.embedder = embedder
        self.evidence_threshold = evidence_threshold
        self.vector_weight = vector_weight

    def search(
        self,
        query: str,
        scope_folder_id: str,
        limit: int = 5,
        scope: AccessScope | None = None,
    ) -> dict[str, Any]:
        if not query.strip():
            raise ValueError("query must not be empty")
        if not scope_folder_id.strip():
            raise ValueError("scope_folder_id must not be empty")
        candidate_limit = max(limit * 4, 20)
        keyword = self.store.keyword_scores(
            query,
            candidate_limit,
            scope,
            scope_folder_id,
        )
        vector = self.store.vector_scores(
            self.embedder.embed_query(query),
            candidate_limit,
            scope,
            scope_folder_id,
        )
        candidate_ids = set(keyword) | set(vector)
        scores = {
            chunk_id: self.vector_weight * vector.get(chunk_id, 0.0)
            + (1.0 - self.vector_weight) * keyword.get(chunk_id, 0.0)
            for chunk_id in candidate_ids
        }
        hits = self.store.search_hits(
            scores,
            limit,
            scope,
            scope_folder_id,
        )
        top_score = hits[0].score if hits else 0.0
        sufficient = bool(hits) and top_score >= self.evidence_threshold
        return {
            "query": query,
            "applied_scope": {
                "caller_profile_id": scope.profile_id if scope else "unrestricted-local",
                "scope_folder_id": scope_folder_id,
                "includes_descendants": True,
            },
            "evidence": {
                "sufficient": sufficient,
                "top_score": round(top_score, 4),
                "threshold": self.evidence_threshold,
                "message": (
                    "Evidence meets the configured retrieval threshold; verify citations and dates."
                    if sufficient
                    else (
                        "Insufficient indexed evidence. Abstain or refine the query; "
                        "do not infer an answer."
                    )
                ),
            },
            "results": [hit.as_dict() for hit in hits] if sufficient else [],
            "candidate_results": [hit.as_dict() for hit in hits] if not sufficient else [],
        }
