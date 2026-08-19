from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _int(name: str, default: int) -> int:
    return int(os.getenv(name, str(default)))


def _float(name: str, default: float) -> float:
    return float(os.getenv(name, str(default)))


@dataclass(frozen=True, slots=True)
class Settings:
    folder_id: str = ""
    shared_drive_id: str | None = None
    db_path: Path = Path("data/index.db")
    gemini_api_key: str = ""
    embed_model: str = "gemini-embedding-001"
    embed_dimensions: int = 768
    chunk_size: int = 700
    chunk_overlap: int = 100
    evidence_threshold: float = 0.35
    service_account_file: Path | None = None
    oauth_client_file: Path | None = None
    oauth_token_file: Path = Path("data/google-oauth-token.json")
    bearer_token: str = ""
    host: str = "127.0.0.1"
    port: int = 8000

    @classmethod
    def from_env(cls) -> Settings:
        def path_or_none(name: str) -> Path | None:
            value = os.getenv(name)
            return Path(value) if value else None

        return cls(
            folder_id=os.getenv("GDRIVE_FOLDER_ID", ""),
            shared_drive_id=os.getenv("GDRIVE_SHARED_DRIVE_ID") or None,
            db_path=Path(os.getenv("GDRIVE_RAG_DB_PATH", "data/index.db")),
            gemini_api_key=os.getenv("GEMINI_API_KEY", ""),
            embed_model=os.getenv("GDRIVE_RAG_EMBED_MODEL", "gemini-embedding-001"),
            embed_dimensions=_int("GDRIVE_RAG_EMBED_DIMENSIONS", 768),
            chunk_size=_int("GDRIVE_RAG_CHUNK_SIZE", 700),
            chunk_overlap=_int("GDRIVE_RAG_CHUNK_OVERLAP", 100),
            evidence_threshold=_float("GDRIVE_RAG_EVIDENCE_THRESHOLD", 0.35),
            service_account_file=path_or_none("GOOGLE_SERVICE_ACCOUNT_FILE"),
            oauth_client_file=path_or_none("GOOGLE_OAUTH_CLIENT_FILE"),
            oauth_token_file=Path(
                os.getenv("GOOGLE_OAUTH_TOKEN_FILE", "data/google-oauth-token.json")
            ),
            bearer_token=os.getenv("GDRIVE_RAG_BEARER_TOKEN", ""),
            host=os.getenv("GDRIVE_RAG_HOST", "127.0.0.1"),
            port=_int("GDRIVE_RAG_PORT", 8000),
        )

    def require_sync(self) -> None:
        missing = []
        if not self.folder_id:
            missing.append("GDRIVE_FOLDER_ID")
        if not self.gemini_api_key:
            missing.append("GEMINI_API_KEY")
        if not (
            self.service_account_file or self.oauth_client_file or self.oauth_token_file.exists()
        ):
            missing.append("Google service-account or OAuth credentials")
        if missing:
            raise ValueError("Missing sync configuration: " + ", ".join(missing))
