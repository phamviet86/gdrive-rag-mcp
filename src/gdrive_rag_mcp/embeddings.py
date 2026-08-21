from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Any, Protocol, cast

import httpx
from google import genai
from google.genai import types

if TYPE_CHECKING:
    from .config import Settings


@dataclass(frozen=True, slots=True)
class EmbeddingIdentity:
    """Non-secret identity for vectors that must never be mixed in one index."""

    provider: str
    model: str
    dimensions: int
    endpoint: str = ""

    @property
    def fingerprint(self) -> str:
        payload = json.dumps(asdict(self), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode()).hexdigest()

    def as_dict(self) -> dict[str, str | int]:
        return {**asdict(self), "fingerprint": self.fingerprint}


class Embedder(Protocol):
    identity: EmbeddingIdentity
    dimensions: int

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


def _normalize(vector: Sequence[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in vector)) or 1.0
    return [float(value) / norm for value in vector]


def _validate_vectors(
    vectors: Sequence[Sequence[float]], expected_count: int, dimensions: int
) -> list[list[float]]:
    if len(vectors) != expected_count:
        raise RuntimeError(
            f"Embedding provider returned {len(vectors)} vectors; expected {expected_count}"
        )
    if any(len(vector) != dimensions for vector in vectors):
        actual = sorted({len(vector) for vector in vectors})
        raise RuntimeError(
            f"Embedding provider returned dimensions {actual}; configured dimension is {dimensions}"
        )
    return [_normalize(vector) for vector in vectors]


def _batches(texts: Sequence[str], size: int) -> list[Sequence[str]]:
    return [texts[offset : offset + size] for offset in range(0, len(texts), size)]


class GeminiEmbedder:
    def __init__(
        self,
        api_key: str,
        model: str,
        dimensions: int,
        batch_size: int = 32,
        timeout_seconds: float = 60.0,
    ) -> None:
        self.client = genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(timeout=int(timeout_seconds * 1000)),
        )
        self.model = model
        self.dimensions = dimensions
        self.batch_size = batch_size
        self.identity = EmbeddingIdentity("gemini", model, dimensions, "google-gemini-api")

    def _embed(self, texts: Sequence[str], task_type: str) -> list[list[float]]:
        vectors: list[list[float]] = []
        for batch in _batches(texts, self.batch_size):
            response = self.client.models.embed_content(
                model=self.model,
                contents=cast(Any, list(batch)),
                config=types.EmbedContentConfig(
                    task_type=task_type,
                    output_dimensionality=self.dimensions,
                ),
            )
            if not response.embeddings:
                raise RuntimeError("Gemini returned no embeddings")
            vectors.extend(list(item.values or []) for item in response.embeddings)
        return _validate_vectors(vectors, len(texts), self.dimensions)

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return self._embed(texts, "RETRIEVAL_DOCUMENT")

    def embed_query(self, text: str) -> list[float]:
        return self._embed([text], "RETRIEVAL_QUERY")[0]


class OpenAICompatibleEmbedder:
    """Client for the documented POST /embeddings JSON contract."""

    def __init__(
        self,
        model: str,
        dimensions: int,
        base_url: str,
        api_key: str = "",
        batch_size: int = 64,
        timeout_seconds: float = 60.0,
        send_dimensions: bool = True,
        query_input_type: str = "",
        document_input_type: str = "",
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.model = model
        self.dimensions = dimensions
        self.batch_size = batch_size
        self.send_dimensions = send_dimensions
        self.query_input_type = query_input_type
        self.document_input_type = document_input_type
        normalized_url = base_url.rstrip("/")
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self.client = httpx.Client(
            base_url=normalized_url,
            headers=headers,
            timeout=timeout_seconds,
            transport=transport,
        )
        self.identity = EmbeddingIdentity("openai-compatible", model, dimensions, normalized_url)

    def _embed(self, texts: Sequence[str], input_type: str = "") -> list[list[float]]:
        vectors: list[list[float]] = []
        for batch in _batches(texts, self.batch_size):
            body: dict[str, Any] = {
                "model": self.model,
                "input": list(batch),
                "encoding_format": "float",
            }
            if self.send_dimensions:
                body["dimensions"] = self.dimensions
            if input_type:
                body["input_type"] = input_type
            response = self.client.post("/embeddings", json=body)
            if response.is_error:
                raise RuntimeError(
                    f"Embedding endpoint returned HTTP {response.status_code}; "
                    "response body omitted"
                )
            payload = response.json()
            data = payload.get("data") if isinstance(payload, dict) else None
            if not isinstance(data, list):
                raise RuntimeError("Embedding endpoint response is missing a data array")
            ordered = sorted(data, key=lambda item: int(item.get("index", -1)))
            vectors.extend(item.get("embedding", []) for item in ordered)
        return _validate_vectors(vectors, len(texts), self.dimensions)

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return self._embed(texts, self.document_input_type)

    def embed_query(self, text: str) -> list[float]:
        return self._embed([text], self.query_input_type)[0]


class SentenceTransformersEmbedder:
    def __init__(
        self,
        model: str,
        dimensions: int,
        batch_size: int = 32,
        device: str = "",
    ) -> None:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as error:
            raise RuntimeError(
                "Sentence Transformers provider requires the optional dependency: "
                "pip install 'gdrive-rag-mcp[sentence-transformers]'"
            ) from error
        self.model = SentenceTransformer(model, device=device or None)
        self.dimensions = dimensions
        self.batch_size = batch_size
        self.device = device or None
        self.identity = EmbeddingIdentity("sentence-transformers", model, dimensions, "local")

    def _encode(self, texts: Sequence[str], query: bool) -> list[list[float]]:
        method = self.model.encode_query if query else self.model.encode_document
        values = method(
            list(texts),
            batch_size=self.batch_size,
            show_progress_bar=False,
            convert_to_numpy=True,
            normalize_embeddings=True,
            truncate_dim=self.dimensions,
            device=self.device,
        )
        vectors = cast(Any, values).tolist()
        return _validate_vectors(vectors, len(texts), self.dimensions)

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return self._encode(texts, query=False)

    def embed_query(self, text: str) -> list[float]:
        return self._encode([text], query=True)[0]


class HashingEmbedder:
    """Deterministic, Unicode-safe offline test embedder; not for production."""

    def __init__(self, dimensions: int = 64, model: str = "sha256-token-hash-v1") -> None:
        self.dimensions = dimensions
        self.identity = EmbeddingIdentity("test", model, dimensions, "local")

    def _one(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        for token in re.findall(r"\w+", text.casefold(), flags=re.UNICODE):
            digest = hashlib.sha256(token.encode()).digest()
            index = int.from_bytes(digest[:4], "big") % self.dimensions
            vector[index] += 1.0 if digest[4] & 1 else -1.0
        return _normalize(vector)

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._one(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._one(text)


def create_embedder(settings: Settings) -> Embedder:
    provider = settings.embed_provider
    if provider == "gemini":
        return GeminiEmbedder(
            api_key=settings.embedding_api_key(required=True),
            model=settings.embed_model,
            dimensions=settings.embed_dimensions,
            batch_size=settings.embed_batch_size,
            timeout_seconds=settings.embed_timeout_seconds,
        )
    if provider == "openai-compatible":
        return OpenAICompatibleEmbedder(
            api_key=settings.embedding_api_key(required=False),
            model=settings.embed_model,
            dimensions=settings.embed_dimensions,
            base_url=settings.embed_base_url,
            batch_size=settings.embed_batch_size,
            timeout_seconds=settings.embed_timeout_seconds,
            send_dimensions=settings.embed_send_dimensions,
            query_input_type=settings.embed_query_input_type,
            document_input_type=settings.embed_document_input_type,
        )
    if provider == "sentence-transformers":
        return SentenceTransformersEmbedder(
            model=settings.embed_model,
            dimensions=settings.embed_dimensions,
            batch_size=settings.embed_batch_size,
            device=settings.embed_device,
        )
    raise ValueError(f"Unsupported embedding provider: {provider}")
