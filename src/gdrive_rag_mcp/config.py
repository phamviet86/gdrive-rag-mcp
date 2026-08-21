from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from .access import AccessPolicy, AccessScope
from .embeddings import EmbeddingIdentity

SUPPORTED_EMBED_PROVIDERS = {"gemini", "openai-compatible", "sentence-transformers"}


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


def _csv(name: str, default: str) -> tuple[str, ...]:
    values = tuple(item.strip() for item in os.getenv(name, default).split(",") if item.strip())
    if not values:
        raise ValueError(f"{name} must contain at least one value")
    return values


def _provider(value: str) -> str:
    normalized = value.strip().casefold().replace("_", "-")
    if normalized not in SUPPORTED_EMBED_PROVIDERS:
        choices = ", ".join(sorted(SUPPORTED_EMBED_PROVIDERS))
        raise ValueError(f"GDRIVE_RAG_EMBED_PROVIDER must be one of: {choices}")
    return normalized


def _profile_path(profile: str) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", profile):
        raise ValueError("GDRIVE_RAG_INDEX_PROFILE may contain only letters, numbers, ., _, and -")
    return Path("data/index.db" if profile == "default" else f"data/index-{profile}.db")


@dataclass(frozen=True, slots=True)
class Settings:
    folder_id: str = ""
    shared_drive_id: str | None = None
    db_path: Path = Path("data/index.db")
    index_profile: str = "default"
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
    service_account_file: Path | None = None
    oauth_client_file: Path | None = None
    oauth_token_file: Path = Path("data/google-oauth-token.json")
    bearer_token: str = ""
    access_policy_file: Path | None = None
    profile_id: str = "default"
    allowed_owner_profile_ids: tuple[str, ...] = ("self", "shared")
    allowed_business_functions: tuple[str, ...] = ("*",)
    allowed_para_categories: tuple[str, ...] = ("*",)
    scope_layout: str = "profile-business-para"
    host: str = "127.0.0.1"
    port: int = 8000

    @classmethod
    def from_env(cls) -> Settings:
        def path_or_none(name: str) -> Path | None:
            value = os.getenv(name)
            return Path(value) if value else None

        provider = _provider(os.getenv("GDRIVE_RAG_EMBED_PROVIDER", "gemini"))
        default_key_env = "GEMINI_API_KEY" if provider == "gemini" else "OPENAI_API_KEY"
        profile = os.getenv("GDRIVE_RAG_INDEX_PROFILE", "default")
        db_path = (
            Path(os.environ["GDRIVE_RAG_DB_PATH"])
            if "GDRIVE_RAG_DB_PATH" in os.environ
            else _profile_path(profile)
        )
        settings = cls(
            folder_id=os.getenv("GDRIVE_FOLDER_ID", ""),
            shared_drive_id=os.getenv("GDRIVE_SHARED_DRIVE_ID") or None,
            db_path=db_path,
            index_profile=profile,
            embed_provider=provider,
            embed_model=os.getenv("GDRIVE_RAG_EMBED_MODEL", "gemini-embedding-001"),
            embed_dimensions=_int("GDRIVE_RAG_EMBED_DIMENSIONS", 768),
            embed_base_url=os.getenv(
                "GDRIVE_RAG_EMBED_BASE_URL", "https://api.openai.com/v1"
            ).rstrip("/"),
            embed_api_key_env=os.getenv("GDRIVE_RAG_EMBED_API_KEY_ENV", default_key_env),
            embed_batch_size=_int("GDRIVE_RAG_EMBED_BATCH_SIZE", 32),
            embed_timeout_seconds=_float("GDRIVE_RAG_EMBED_TIMEOUT_SECONDS", 60.0),
            embed_send_dimensions=_bool("GDRIVE_RAG_EMBED_SEND_DIMENSIONS", True),
            embed_query_input_type=os.getenv("GDRIVE_RAG_EMBED_QUERY_INPUT_TYPE", ""),
            embed_document_input_type=os.getenv("GDRIVE_RAG_EMBED_DOCUMENT_INPUT_TYPE", ""),
            embed_device=os.getenv("GDRIVE_RAG_EMBED_DEVICE", ""),
            chunk_size=_int("GDRIVE_RAG_CHUNK_SIZE", 700),
            chunk_overlap=_int("GDRIVE_RAG_CHUNK_OVERLAP", 100),
            evidence_threshold=_float("GDRIVE_RAG_EVIDENCE_THRESHOLD", 0.35),
            service_account_file=path_or_none("GOOGLE_SERVICE_ACCOUNT_FILE"),
            oauth_client_file=path_or_none("GOOGLE_OAUTH_CLIENT_FILE"),
            oauth_token_file=Path(
                os.getenv("GOOGLE_OAUTH_TOKEN_FILE", "data/google-oauth-token.json")
            ),
            bearer_token=os.getenv("GDRIVE_RAG_BEARER_TOKEN", ""),
            access_policy_file=path_or_none("GDRIVE_RAG_ACCESS_POLICY_FILE"),
            profile_id=os.getenv("GDRIVE_RAG_PROFILE_ID", "default"),
            allowed_owner_profile_ids=_csv("GDRIVE_RAG_ALLOWED_OWNER_PROFILE_IDS", "self,shared"),
            allowed_business_functions=_csv("GDRIVE_RAG_ALLOWED_BUSINESS_FUNCTIONS", "*"),
            allowed_para_categories=_csv("GDRIVE_RAG_ALLOWED_PARA_CATEGORIES", "*"),
            scope_layout=os.getenv("GDRIVE_RAG_SCOPE_LAYOUT", "profile-business-para").strip(),
            host=os.getenv("GDRIVE_RAG_HOST", "127.0.0.1"),
            port=_int("GDRIVE_RAG_PORT", 8000),
        )
        settings.validate_embedding()
        return settings

    def validate_embedding(self) -> None:
        _provider(self.embed_provider)
        if not self.embed_model.strip():
            raise ValueError("GDRIVE_RAG_EMBED_MODEL must not be empty")
        if self.embed_dimensions <= 0:
            raise ValueError("GDRIVE_RAG_EMBED_DIMENSIONS must be positive")
        if self.embed_batch_size <= 0:
            raise ValueError("GDRIVE_RAG_EMBED_BATCH_SIZE must be positive")
        if self.embed_timeout_seconds <= 0:
            raise ValueError("GDRIVE_RAG_EMBED_TIMEOUT_SECONDS must be positive")
        if self.embed_provider == "openai-compatible" and not self.embed_base_url:
            raise ValueError("GDRIVE_RAG_EMBED_BASE_URL is required for openai-compatible")
        parsed_url = urlsplit(self.embed_base_url)
        if self.embed_provider == "openai-compatible" and (
            parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc
        ):
            raise ValueError("GDRIVE_RAG_EMBED_BASE_URL must be an HTTP(S) API base URL")
        if parsed_url.username or parsed_url.password:
            raise ValueError("Do not put credentials in GDRIVE_RAG_EMBED_BASE_URL")
        if self.embed_provider == "openai-compatible" and (parsed_url.query or parsed_url.fragment):
            raise ValueError(
                "GDRIVE_RAG_EMBED_BASE_URL must not contain a query string or fragment"
            )
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", self.embed_api_key_env):
            raise ValueError("GDRIVE_RAG_EMBED_API_KEY_ENV must be an environment variable name")
        _profile_path(self.index_profile)
        if self.scope_layout not in {"profile-business-para", "flat"}:
            raise ValueError("GDRIVE_RAG_SCOPE_LAYOUT must be profile-business-para or flat")
        self.default_access_scope()

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

    def default_access_scope(self) -> AccessScope:
        return AccessScope.create(
            self.profile_id,
            self.allowed_owner_profile_ids,
            self.allowed_business_functions,
            self.allowed_para_categories,
        )

    def access_policy(self) -> AccessPolicy:
        if self.access_policy_file:
            return AccessPolicy.from_file(self.access_policy_file)
        return AccessPolicy.from_single_token(self.bearer_token, self.default_access_scope())

    def require_sync(self) -> None:
        missing = []
        if not self.folder_id:
            missing.append("GDRIVE_FOLDER_ID")
        if self.embed_provider == "gemini" and not os.getenv(self.embed_api_key_env):
            missing.append(self.embed_api_key_env)
        if not (
            self.service_account_file or self.oauth_client_file or self.oauth_token_file.exists()
        ):
            missing.append("Google service-account or OAuth credentials")
        if missing:
            raise ValueError("Missing sync configuration: " + ", ".join(missing))
