from __future__ import annotations

import hashlib
import io
from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast

from docx import Document
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google.oauth2.service_account import Credentials as ServiceAccountCredentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from openpyxl import load_workbook
from pypdf import PdfReader

from .config import Settings
from .models import SourceDocument

SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]
FOLDER_MIME = "application/vnd.google-apps.folder"
GOOGLE_DOC = "application/vnd.google-apps.document"
GOOGLE_SHEET = "application/vnd.google-apps.spreadsheet"
PDF = "application/pdf"
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
TEXT_MIMES = {"text/plain", "text/markdown", "text/x-markdown"}
SUPPORTED_MIMES = {GOOGLE_DOC, GOOGLE_SHEET, PDF, DOCX, *TEXT_MIMES}


def google_credentials(settings: Settings, interactive: bool = False) -> Any:
    if settings.service_account_file:
        return ServiceAccountCredentials.from_service_account_file(  # type: ignore[no-untyped-call]
            str(settings.service_account_file), scopes=SCOPES
        )
    credentials: Credentials | None = None
    if settings.oauth_token_file.exists():
        credentials = Credentials.from_authorized_user_file(  # type: ignore[no-untyped-call]
            str(settings.oauth_token_file), SCOPES
        )
    if credentials and credentials.expired and credentials.refresh_token:
        credentials.refresh(Request())  # type: ignore[no-untyped-call]
    if credentials and credentials.valid:
        return credentials
    if not interactive or not settings.oauth_client_file:
        raise ValueError(
            "Valid Google credentials not found. Configure a service account or run "
            "`gdrive-rag-mcp auth-google`."
        )
    flow = InstalledAppFlow.from_client_secrets_file(str(settings.oauth_client_file), SCOPES)
    credentials = flow.run_local_server(port=0)
    settings.oauth_token_file.parent.mkdir(parents=True, exist_ok=True)
    settings.oauth_token_file.write_text(credentials.to_json(), encoding="utf-8")
    settings.oauth_token_file.chmod(0o600)
    return credentials


class GoogleDriveSource:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.service = build(
            "drive", "v3", credentials=google_credentials(settings), cache_discovery=False
        )

    def _list_children(self, folder_id: str) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        page_token: str | None = None
        while True:
            kwargs: dict[str, Any] = {
                "q": f"'{folder_id}' in parents and trashed = false",
                "fields": (
                    "nextPageToken,files(id,name,mimeType,modifiedTime,md5Checksum,"
                    "webViewLink,size)"
                ),
                "pageSize": 1000,
                "supportsAllDrives": True,
                "includeItemsFromAllDrives": True,
                "pageToken": page_token,
            }
            if self.settings.shared_drive_id:
                kwargs.update(
                    {
                        "corpora": "drive",
                        "driveId": self.settings.shared_drive_id,
                    }
                )
            response = self.service.files().list(**kwargs).execute()
            result.extend(response.get("files", []))
            page_token = response.get("nextPageToken")
            if not page_token:
                return result

    def _metadata(self) -> Iterator[dict[str, Any]]:
        pending = [self.settings.folder_id]
        seen: set[str] = set()
        while pending:
            folder_id = pending.pop()
            if folder_id in seen:
                continue
            seen.add(folder_id)
            for item in self._list_children(folder_id):
                if item["mimeType"] == FOLDER_MIME:
                    pending.append(item["id"])
                elif item["mimeType"] in SUPPORTED_MIMES:
                    yield item

    def _bytes(self, file_id: str, mime_type: str) -> bytes:
        if mime_type == GOOGLE_DOC:
            result = (
                self.service.files().export_media(fileId=file_id, mimeType="text/plain").execute()
            )
            return cast(bytes, result)
        if mime_type == GOOGLE_SHEET:
            export_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            result = (
                self.service.files().export_media(fileId=file_id, mimeType=export_type).execute()
            )
            return cast(bytes, result)
        result = self.service.files().get_media(fileId=file_id, supportsAllDrives=True).execute()
        return cast(bytes, result)

    @staticmethod
    def _extract(content: bytes, mime_type: str) -> str:
        if mime_type in TEXT_MIMES or mime_type == GOOGLE_DOC:
            return content.decode("utf-8", errors="replace")
        if mime_type == PDF:
            return "\n\n".join(
                page.extract_text() or "" for page in PdfReader(io.BytesIO(content)).pages
            )
        if mime_type == DOCX:
            document = Document(io.BytesIO(content))
            paragraphs = [paragraph.text for paragraph in document.paragraphs]
            tables = [
                "\n".join("\t".join(cell.text for cell in row.cells) for row in table.rows)
                for table in document.tables
            ]
            return "\n\n".join([*paragraphs, *tables])
        if mime_type == GOOGLE_SHEET:
            workbook = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
            sections = []
            for sheet in workbook.worksheets:
                rows = [
                    "\t".join("" if value is None else str(value) for value in row)
                    for row in sheet.iter_rows(values_only=True)
                ]
                sections.append(f"# Sheet: {sheet.title}\n" + "\n".join(rows))
            return "\n\n".join(sections)
        raise ValueError(f"Unsupported MIME type: {mime_type}")

    def documents(self) -> Iterator[SourceDocument]:
        for item in self._metadata():
            content = self._bytes(item["id"], item["mimeType"])
            checksum = (
                item.get("md5Checksum")
                or hashlib.sha256(
                    (item.get("modifiedTime", "") + str(item.get("size", ""))).encode()
                ).hexdigest()
            )
            yield SourceDocument(
                id=item["id"],
                name=item["name"],
                mime_type=item["mimeType"],
                modified_time=item.get("modifiedTime", ""),
                checksum=checksum,
                web_url=item.get("webViewLink") or f"https://drive.google.com/open?id={item['id']}",
                text=self._extract(content, item["mimeType"]),
            )


def run_oauth(settings: Settings) -> Path:
    google_credentials(settings, interactive=True)
    return settings.oauth_token_file
