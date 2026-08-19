from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Sequence
from typing import Any, Protocol, cast

from google import genai
from google.genai import types


class Embedder(Protocol):
    dimensions: int

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


class GeminiEmbedder:
    def __init__(self, api_key: str, model: str, dimensions: int) -> None:
        self.client = genai.Client(api_key=api_key)
        self.model = model
        self.dimensions = dimensions

    def _embed(self, texts: Sequence[str], task_type: str) -> list[list[float]]:
        response = self.client.models.embed_content(
            model=self.model,
            contents=cast(Any, list(texts)),
            config=types.EmbedContentConfig(
                task_type=task_type,
                output_dimensionality=self.dimensions,
            ),
        )
        if not response.embeddings:
            raise RuntimeError("Gemini returned no embeddings")
        return [list(item.values or []) for item in response.embeddings]

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return self._embed(texts, "RETRIEVAL_DOCUMENT")

    def embed_query(self, text: str) -> list[float]:
        return self._embed([text], "RETRIEVAL_QUERY")[0]


class HashingEmbedder:
    """Deterministic, offline test/smoke embedder; not intended for production."""

    def __init__(self, dimensions: int = 64) -> None:
        self.dimensions = dimensions

    def _one(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        for token in re.findall(r"\w+", text.casefold(), flags=re.UNICODE):
            digest = hashlib.sha256(token.encode()).digest()
            index = int.from_bytes(digest[:4], "big") % self.dimensions
            vector[index] += 1.0 if digest[4] & 1 else -1.0
        norm = math.sqrt(sum(value * value for value in vector)) or 1.0
        return [value / norm for value in vector]

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._one(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._one(text)
