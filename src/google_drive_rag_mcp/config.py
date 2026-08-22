from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from .embeddings import EmbeddingIdentity

SUPPORTED_EMBED_PROVIDERS = {"gemini", "openai-compatible", "sentence-transformers"}
MAX_DRIVE_API_NUM_RETRIES = 10


def _int(name: str, default: int) -> int:
    return int(os.getenv(name, str(default)))


def _float(name: str, default: float) -> float:
    return float(os.getenv(name, str(default)))


def _bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    if value.casefold() in {"1", "true", "yes", "on"}:
        return True
    if value.casefold() in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be true or false")


def _provider(value: str) -> str:
    normalized = value.strip().casefold().replace("_", "-")
    if normalized not in SUPPORTED_EMBED_PROVIDERS:
        choices = ", ".join(sorted(SUPPORTED_EMBED_PROVIDERS))
        raise ValueError(f"GOOGLE_DRIVE_RAG_EMBED_PROVIDER must be one of: {choices}")
    return normalized


@dataclass(frozen=True, slots=True)
class Settings:
    folder_id: str = ""
    shared_drive_id: str | None = None
    db_path: Path = Path("data/index.db")
    embed_provider: str = "gemini"
    embed_model: str = "gemini-embedding-001"
    embed_dimensions: int = 768
    embed_base_url: str = "https://api.openai.com/v1"
    embed_api_key_env: str = "GEMINI_API_KEY"
    embed_batch_size: int = 32
    embed_timeout_seconds: float = 60.0
    embed_send_dimensions: bool = True
    embed_query_input_type: str = ""
    embed_document_input_type: str = ""
    embed_device: str = ""
    chunk_size: int = 700
    chunk_overlap: int = 100
    evidence_threshold: float = 0.35
    drive_api_num_retries: int = 5
    drive_download_chunk_size: int = 8 * 1024 * 1024
    token_file: Path = Path.home() / ".config/google-drive-rag-mcp/token.json"

    def __post_init__(self) -> None:
        object.__setattr__(self, "db_path", self.db_path.expanduser())
        object.__setattr__(self, "token_file", self.token_file.expanduser())

    @classmethod
    def from_env(cls) -> Settings:
        provider = _provider(os.getenv("GOOGLE_DRIVE_RAG_EMBED_PROVIDER", "gemini"))
        default_key_env = "GEMINI_API_KEY" if provider == "gemini" else "OPENAI_API_KEY"
        settings = cls(
            folder_id=os.getenv("GOOGLE_DRIVE_FOLDER_ID", ""),
            shared_drive_id=os.getenv("GOOGLE_DRIVE_SHARED_DRIVE_ID") or None,
            db_path=Path(os.getenv("GOOGLE_DRIVE_RAG_DB_PATH", "data/index.db")).expanduser(),
            embed_provider=provider,
            embed_model=os.getenv("GOOGLE_DRIVE_RAG_EMBED_MODEL", "gemini-embedding-001"),
            embed_dimensions=_int("GOOGLE_DRIVE_RAG_EMBED_DIMENSIONS", 768),
            embed_base_url=os.getenv(
                "GOOGLE_DRIVE_RAG_EMBED_BASE_URL", "https://api.openai.com/v1"
            ).rstrip("/"),
            embed_api_key_env=os.getenv("GOOGLE_DRIVE_RAG_EMBED_API_KEY_ENV", default_key_env),
            embed_batch_size=_int("GOOGLE_DRIVE_RAG_EMBED_BATCH_SIZE", 32),
            embed_timeout_seconds=_float("GOOGLE_DRIVE_RAG_EMBED_TIMEOUT_SECONDS", 60.0),
            embed_send_dimensions=_bool("GOOGLE_DRIVE_RAG_EMBED_SEND_DIMENSIONS", True),
            embed_query_input_type=os.getenv("GOOGLE_DRIVE_RAG_EMBED_QUERY_INPUT_TYPE", ""),
            embed_document_input_type=os.getenv("GOOGLE_DRIVE_RAG_EMBED_DOCUMENT_INPUT_TYPE", ""),
            embed_device=os.getenv("GOOGLE_DRIVE_RAG_EMBED_DEVICE", ""),
            chunk_size=_int("GOOGLE_DRIVE_RAG_CHUNK_SIZE", 700),
            chunk_overlap=_int("GOOGLE_DRIVE_RAG_CHUNK_OVERLAP", 100),
            evidence_threshold=_float("GOOGLE_DRIVE_RAG_EVIDENCE_THRESHOLD", 0.35),
            drive_api_num_retries=_int("GOOGLE_DRIVE_API_NUM_RETRIES", 5),
            drive_download_chunk_size=_int("GOOGLE_DRIVE_DOWNLOAD_CHUNK_SIZE", 8 * 1024 * 1024),
            token_file=Path(
                os.getenv(
                    "GOOGLE_TOKEN_FILE",
                    str(Path.home() / ".config/google-drive-rag-mcp/token.json"),
                )
            ).expanduser(),
        )
        settings.validate_embedding()
        return settings

    def validate_embedding(self) -> None:
        _provider(self.embed_provider)
        if not self.embed_model.strip():
            raise ValueError("GOOGLE_DRIVE_RAG_EMBED_MODEL must not be empty")
        if self.embed_dimensions <= 0:
            raise ValueError("GOOGLE_DRIVE_RAG_EMBED_DIMENSIONS must be positive")
        if self.embed_batch_size <= 0:
            raise ValueError("GOOGLE_DRIVE_RAG_EMBED_BATCH_SIZE must be positive")
        if self.embed_timeout_seconds <= 0:
            raise ValueError("GOOGLE_DRIVE_RAG_EMBED_TIMEOUT_SECONDS must be positive")
        if not 0 <= self.drive_api_num_retries <= MAX_DRIVE_API_NUM_RETRIES:
            raise ValueError(
                "GOOGLE_DRIVE_API_NUM_RETRIES must be an integer from 0 to "
                f"{MAX_DRIVE_API_NUM_RETRIES}"
            )
        if self.drive_download_chunk_size <= 0:
            raise ValueError("GOOGLE_DRIVE_DOWNLOAD_CHUNK_SIZE must be positive")
        if self.embed_provider == "openai-compatible" and not self.embed_base_url:
            raise ValueError("GOOGLE_DRIVE_RAG_EMBED_BASE_URL is required for openai-compatible")
        parsed_url = urlsplit(self.embed_base_url)
        if self.embed_provider == "openai-compatible" and (
            parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc
        ):
            raise ValueError("GOOGLE_DRIVE_RAG_EMBED_BASE_URL must be an HTTP(S) API base URL")
        if parsed_url.username or parsed_url.password:
            raise ValueError("Do not put credentials in GOOGLE_DRIVE_RAG_EMBED_BASE_URL")
        if self.embed_provider == "openai-compatible" and (parsed_url.query or parsed_url.fragment):
            raise ValueError(
                "GOOGLE_DRIVE_RAG_EMBED_BASE_URL must not contain a query string or fragment"
            )
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", self.embed_api_key_env):
            raise ValueError(
                "GOOGLE_DRIVE_RAG_EMBED_API_KEY_ENV must be an environment variable name"
            )

    def embedding_api_key(self, required: bool) -> str:
        value = os.getenv(self.embed_api_key_env, "")
        if required and not value:
            raise ValueError(
                f"Embedding provider {self.embed_provider!r} requires secret environment variable "
                f"{self.embed_api_key_env}"
            )
        return value

    def embedding_identity(self) -> EmbeddingIdentity:
        endpoint = {
            "gemini": "google-gemini-api",
            "openai-compatible": self.embed_base_url.rstrip("/"),
            "sentence-transformers": "local",
        }[self.embed_provider]
        return EmbeddingIdentity(
            self.embed_provider, self.embed_model, self.embed_dimensions, endpoint
        )

    def require_sync(self) -> None:
        missing = []
        if not self.folder_id:
            missing.append("GOOGLE_DRIVE_FOLDER_ID")
        if self.embed_provider == "gemini" and not os.getenv(self.embed_api_key_env):
            missing.append(self.embed_api_key_env)
        if not self.token_file.expanduser().exists():
            missing.append("Google OAuth token; run google-drive-rag-mcp-auth --client-secret FILE")
        if missing:
            raise ValueError("Missing sync configuration: " + ", ".join(missing))
