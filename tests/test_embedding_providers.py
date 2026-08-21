from __future__ import annotations

import builtins
from typing import Any

import httpx
import pytest

from google_drive_rag_mcp.config import Settings
from google_drive_rag_mcp.embeddings import (
    GeminiEmbedder,
    OpenAICompatibleEmbedder,
    SentenceTransformersEmbedder,
    create_embedder,
)


def test_environment_defaults_to_gemini(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in (
        "GOOGLE_DRIVE_RAG_EMBED_PROVIDER",
        "GOOGLE_DRIVE_RAG_EMBED_MODEL",
        "GOOGLE_DRIVE_RAG_EMBED_DIMENSIONS",
        "GOOGLE_DRIVE_RAG_EMBED_API_KEY_ENV",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "test-placeholder")

    settings = Settings.from_env()
    embedder = create_embedder(settings)

    assert settings.embed_provider == "gemini"
    assert settings.embed_model == "gemini-embedding-001"
    assert settings.embed_dimensions == 768
    assert settings.embed_api_key_env == "GEMINI_API_KEY"
    assert isinstance(embedder, GeminiEmbedder)


def test_provider_configuration_validation() -> None:
    with pytest.raises(ValueError, match="Unsupported|one of"):
        Settings(embed_provider="unknown").validate_embedding()
    with pytest.raises(ValueError, match="positive"):
        Settings(embed_dimensions=0).validate_embedding()
    with pytest.raises(ValueError, match="BASE_URL"):
        Settings(embed_provider="openai-compatible", embed_base_url="").validate_embedding()
    with pytest.raises(ValueError, match="credentials"):
        Settings(
            embed_provider="openai-compatible",
            embed_base_url="https://user:password@example.test/v1",
        ).validate_embedding()
    with pytest.raises(ValueError, match="query string"):
        Settings(
            embed_provider="openai-compatible",
            embed_base_url="https://example.test/v1?token=do-not-put-secrets-here",
        ).validate_embedding()


def test_named_profile_derives_separate_database_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GOOGLE_DRIVE_RAG_INDEX_PROFILE", "local-multilingual")
    monkeypatch.delenv("GOOGLE_DRIVE_RAG_DB_PATH", raising=False)
    settings = Settings.from_env()
    assert settings.db_path.as_posix() == "data/index-local-multilingual.db"


def test_openai_compatible_contract_batches_normalizes_and_sends_dimensions() -> None:
    requests: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = __import__("json").loads(request.content)
        requests.append(body)
        data = [
            {"object": "embedding", "index": index, "embedding": [3.0, 4.0, 0.0]}
            for index, _ in enumerate(body["input"])
        ]
        return httpx.Response(200, json={"object": "list", "data": data, "model": body["model"]})

    embedder = OpenAICompatibleEmbedder(
        model="multilingual-model",
        dimensions=3,
        base_url="https://embeddings.example.test/v1",
        api_key="test-placeholder",
        batch_size=2,
        document_input_type="search_document",
        transport=httpx.MockTransport(handler),
    )

    vectors = embedder.embed_documents(["English", "Tiếng Việt", "العربية"])

    assert len(requests) == 2
    assert all(request["dimensions"] == 3 for request in requests)
    assert all(request["input_type"] == "search_document" for request in requests)
    assert vectors == [[0.6, 0.8, 0.0]] * 3


def test_factory_selects_openai_compatible_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EMBEDDING_TEST_API_KEY", "test-placeholder")
    settings = Settings(
        embed_provider="openai-compatible",
        embed_model="multilingual-model",
        embed_dimensions=3,
        embed_base_url="https://embeddings.example.test/v1",
        embed_api_key_env="EMBEDDING_TEST_API_KEY",
    )

    embedder = create_embedder(settings)

    assert isinstance(embedder, OpenAICompatibleEmbedder)
    assert embedder.identity == settings.embedding_identity()


def test_openai_identity_canonicalizes_trailing_base_url_slash() -> None:
    settings = Settings(
        embed_provider="openai-compatible",
        embed_model="model",
        embed_dimensions=3,
        embed_base_url="https://embeddings.example.test/v1/",
    )

    assert settings.embedding_identity().endpoint == "https://embeddings.example.test/v1"


def test_openai_compatible_dimension_mismatch_is_actionable() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"data": [{"index": 0, "embedding": [1.0, 2.0]}]},
        )

    embedder = OpenAICompatibleEmbedder(
        model="wrong-size",
        dimensions=3,
        base_url="https://embeddings.example.test/v1",
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(RuntimeError, match="configured dimension is 3"):
        embedder.embed_query("query")


def test_sentence_transformers_missing_extra_has_install_hint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_import = builtins.__import__

    def blocked_import(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "sentence_transformers":
            raise ImportError("blocked for test")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", blocked_import)
    with pytest.raises(RuntimeError, match=r"\[sentence-transformers\]"):
        SentenceTransformersEmbedder("example/model", 384)
