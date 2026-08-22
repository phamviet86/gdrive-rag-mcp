from __future__ import annotations

import json
import stat
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import typer
from googleapiclient.errors import HttpError

from google_drive_rag_mcp import cli, drive
from google_drive_rag_mcp import service as service_module
from google_drive_rag_mcp.config import Settings
from google_drive_rag_mcp.drive import (
    DownloadRestrictedError,
    DriveAPIError,
    GoogleDriveSource,
    IncompleteSearchError,
    google_credentials,
)
from google_drive_rag_mcp.indexer import Indexer
from google_drive_rag_mcp.service import KnowledgeService


class Response(dict[str, str]):
    status: int

    def __init__(self, status: int) -> None:
        super().__init__()
        self.status = status
        self.reason = "error"


def http_error(status: int, reason: str) -> HttpError:
    content = json.dumps(
        {"error": {"errors": [{"reason": reason}], "code": status, "message": "omitted"}}
    ).encode()
    return HttpError(Response(status), content)


def source_settings(**overrides: Any) -> SimpleNamespace:
    values = {
        "folder_id": "root",
        "shared_drive_id": None,
        "drive_api_num_retries": 4,
        "drive_download_chunk_size": 1024,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


@pytest.mark.parametrize(
    ("status", "reason"),
    (
        (403, "rateLimitExceeded"),
        (403, "userRateLimitExceeded"),
        (503, "backendError"),
    ),
)
def test_execute_passes_native_retries_and_parses_error_reasons(status: int, reason: str) -> None:
    observed: list[int] = []

    class Request:
        def execute(self, *, num_retries: int) -> None:
            observed.append(num_retries)
            raise http_error(status, reason)

    source = object.__new__(GoogleDriveSource)
    source.settings = source_settings()

    with pytest.raises(DriveAPIError) as raised:
        source._execute(Request(), "files.get")

    assert observed == [4]
    assert raised.value.status == status
    assert raised.value.reasons == (reason,)


def test_only_not_found_is_treated_as_missing() -> None:
    class Request:
        def __init__(self, error: HttpError) -> None:
            self.error = error

        def execute(self, *, num_retries: int) -> None:
            assert num_retries == 4
            raise self.error

    source = object.__new__(GoogleDriveSource)
    source.settings = source_settings()

    assert (
        source._execute(Request(http_error(404, "notFound")), "files.get", allow_not_found=True)
        is None
    )
    with pytest.raises(DriveAPIError):
        source._execute(
            Request(http_error(403, "insufficientFilePermissions")),
            "files.get",
            allow_not_found=True,
        )


def test_trashed_or_out_of_scope_change_is_not_authorized_for_deletion() -> None:
    source = object.__new__(GoogleDriveSource)
    source._get_item = lambda file_id: {  # type: ignore[method-assign]
        "id": file_id,
        "trashed": True,
        "mimeType": "text/plain",
    }

    document, delete_allowed = source._resolve_document_change("doc")

    assert document is None
    assert not delete_allowed

    source._get_item = lambda file_id: None  # type: ignore[method-assign]
    document, delete_allowed = source._resolve_document_change("not-found")
    assert document is None
    assert delete_allowed


def test_download_uses_chunks_and_native_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[int, int]] = []

    class Downloader:
        def __init__(self, output: Any, request: Any, *, chunksize: int) -> None:
            assert request == "request"
            self.output = output
            self.chunksize = chunksize
            self.index = 0

        def next_chunk(self, *, num_retries: int) -> tuple[None, bool]:
            self.index += 1
            self.output.write(("a" if self.index == 1 else "b").encode())
            calls.append((self.chunksize, num_retries))
            return None, self.index == 2

    monkeypatch.setattr(drive, "MediaIoBaseDownload", Downloader)
    source = object.__new__(GoogleDriveSource)
    source.settings = source_settings()

    assert source._download("request", "files.get_media") == b"ab"
    assert calls == [(1024, 4), (1024, 4)]


def test_drive_source_context_closes_resource_once_on_error() -> None:
    closed = 0

    class Service:
        def close(self) -> None:
            nonlocal closed
            closed += 1

    source = object.__new__(GoogleDriveSource)
    source.service = Service()

    with pytest.raises(RuntimeError, match="sync failed"), source:
        raise RuntimeError("sync failed")
    source.close()

    assert closed == 1


def test_incremental_sync_closes_source_when_changes_fail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    closed = 0

    class Source:
        def changes(self, page_token: str) -> None:
            assert page_token == "page-token"
            raise RuntimeError("changes failed")

        def close(self) -> None:
            nonlocal closed
            closed += 1

    source = Source()
    monkeypatch.setattr(service_module, "GoogleDriveSource", lambda settings: source)
    monkeypatch.setattr(service_module, "Indexer", lambda *args: object())
    service = object.__new__(KnowledgeService)
    service.settings = SimpleNamespace(
        folder_id="root",
        chunk_size=700,
        chunk_overlap=100,
        require_sync=lambda: None,
    )
    service.store = SimpleNamespace(
        get_state=lambda key: "root" if key == "drive_root_folder_id" else "page-token"
    )
    service.embedder = object()

    with pytest.raises(RuntimeError, match="changes failed"):
        service.sync()

    assert closed == 1


def test_full_sync_closes_source_when_indexing_fails() -> None:
    closed = 0

    class Source:
        def start_page_token(self) -> str:
            return "page-token"

        def close(self) -> None:
            nonlocal closed
            closed += 1

    class FailingIndexer:
        def sync(self) -> None:
            raise RuntimeError("indexing failed")

    service = object.__new__(KnowledgeService)
    service.settings = SimpleNamespace(folder_id="root", require_sync=lambda: None)
    service.store = object()

    with pytest.raises(RuntimeError, match="indexing failed"):
        service.full_sync(Source(), FailingIndexer())  # type: ignore[arg-type]

    assert closed == 1


def test_full_sync_closes_source_when_indexer_construction_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    closed = 0

    class Source:
        def close(self) -> None:
            nonlocal closed
            closed += 1

    def fail_to_build_indexer(*args: Any) -> None:
        raise RuntimeError("indexer construction failed")

    monkeypatch.setattr(service_module, "Indexer", fail_to_build_indexer)
    service = object.__new__(KnowledgeService)
    service.settings = SimpleNamespace(
        folder_id="root",
        chunk_size=700,
        chunk_overlap=100,
        require_sync=lambda: None,
    )
    service.store = object()
    service.embedder = object()

    with pytest.raises(RuntimeError, match="construction failed"):
        service.full_sync(Source())  # type: ignore[arg-type]

    assert closed == 1


def test_source_document_requires_download_capability() -> None:
    source = object.__new__(GoogleDriveSource)
    with pytest.raises(DownloadRestrictedError):
        source._source_document({"id": "blocked", "capabilities": {"canDownload": False}})


def test_incomplete_search_aborts_authoritative_listing() -> None:
    class Request:
        def execute(self, *, num_retries: int) -> dict[str, Any]:
            assert num_retries == 4
            return {"files": [{"id": "partial"}], "incompleteSearch": True}

    class Files:
        def list(self, **kwargs: Any) -> Request:
            assert "incompleteSearch" in kwargs["fields"]
            return Request()

    source = object.__new__(GoogleDriveSource)
    source.settings = source_settings()
    source.service = SimpleNamespace(files=lambda: Files())

    with pytest.raises(IncompleteSearchError):
        source._list_children("root")


def test_incomplete_full_scan_never_reaches_authoritative_deletion() -> None:
    deletion_attempted = False

    class PartialSource:
        def documents(self) -> Any:
            raise IncompleteSearchError("partial")

    class Store:
        def document_fingerprints(self) -> dict[str, str]:
            return {}

        def delete_documents_not_in(self, active_ids: set[str]) -> int:
            nonlocal deletion_attempted
            deletion_attempted = True
            return 0

    indexer = Indexer(PartialSource(), Store(), SimpleNamespace(), SimpleNamespace())  # type: ignore[arg-type]

    with pytest.raises(IncompleteSearchError):
        indexer.sync()
    assert not deletion_attempted


def test_list_children_paginates_with_native_retries() -> None:
    calls: list[tuple[str | None, int]] = []

    class Request:
        def __init__(self, page_token: str | None) -> None:
            self.page_token = page_token

        def execute(self, *, num_retries: int) -> dict[str, Any]:
            calls.append((self.page_token, num_retries))
            if self.page_token is None:
                return {"files": [{"id": "one"}], "nextPageToken": "page-2"}
            return {"files": [{"id": "two"}]}

    class Files:
        def list(self, **kwargs: Any) -> Request:
            return Request(kwargs["pageToken"])

    source = object.__new__(GoogleDriveSource)
    source.settings = source_settings()
    source.service = SimpleNamespace(files=lambda: Files())

    assert [item["id"] for item in source._list_children("root")] == ["one", "two"]
    assert calls == [(None, 4), ("page-2", 4)]


def test_expired_oauth_token_is_refreshed_and_saved_atomically(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    token_file = tmp_path / "token.json"
    tmp_path.chmod(0o755)
    token_file.write_text("{}", encoding="utf-8")

    class FakeCredentials:
        expired = True
        valid = False
        refresh_token = "refresh-token"

        def refresh(self, request: Any) -> None:
            assert request == "request"
            self.expired = False
            self.valid = True

        def to_json(self) -> str:
            return '{"token":"refreshed","refresh_token":"refresh-token"}'

    credentials = FakeCredentials()
    monkeypatch.setattr(
        drive.Credentials,
        "from_authorized_user_file",
        lambda path, scopes: credentials,
    )
    monkeypatch.setattr(drive, "Request", lambda: "request")

    result = google_credentials(Settings(token_file=token_file))

    assert result is credentials
    assert json.loads(token_file.read_text(encoding="utf-8"))["token"] == "refreshed"
    assert stat.S_IMODE(token_file.stat().st_mode) == 0o600
    if drive.os.name != "nt":
        assert stat.S_IMODE(tmp_path.stat().st_mode) == 0o700
    assert list(tmp_path.glob(".token.json.*")) == []


@pytest.mark.skipif(drive.os.name == "nt", reason="POSIX permission behavior")
def test_token_directory_permission_failure_is_actionable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original_chmod = Path.chmod

    def fail_for_token_directory(path: Path, mode: int) -> None:
        if path == tmp_path:
            raise PermissionError("read-only filesystem")
        original_chmod(path, mode)

    monkeypatch.setattr(Path, "chmod", fail_for_token_directory)

    with pytest.raises(ValueError, match="Cannot restrict OAuth token directory"):
        drive._secure_token_directory(tmp_path / "token.json")


def test_saved_oauth_token_must_contain_refresh_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    token_file = tmp_path / "token.json"
    token_file.write_text("{}", encoding="utf-8")
    credentials = SimpleNamespace(refresh_token=None)
    monkeypatch.setattr(
        drive.Credentials,
        "from_authorized_user_file",
        lambda path, scopes: credentials,
    )

    with pytest.raises(ValueError, match="refresh token"):
        google_credentials(Settings(token_file=token_file))


def test_interactive_oauth_token_is_saved_atomically(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    token_file = tmp_path / "token.json"
    client_secret = tmp_path / "client_secret.json"
    client_secret.write_text(
        '{"installed":{"client_id":"example","client_secret":"secret"}}',
        encoding="utf-8",
    )
    credentials = SimpleNamespace(
        refresh_token="refresh-token",
        valid=True,
        to_json=lambda: '{"refresh_token":"refresh-token"}',
    )
    flow = SimpleNamespace(run_local_server=lambda port: credentials)
    monkeypatch.setattr(
        drive.InstalledAppFlow,
        "from_client_secrets_file",
        lambda path, scopes: flow,
    )

    result = google_credentials(
        Settings(token_file=token_file),
        interactive=True,
        client_secret_file=client_secret,
    )

    assert result is credentials
    assert stat.S_IMODE(token_file.stat().st_mode) == 0o600
    assert json.loads(token_file.read_text(encoding="utf-8"))["refresh_token"] == "refresh-token"


def test_structured_command_errors_are_emitted_on_stderr(
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fail() -> None:
        raise ValueError("safe failure")

    wrapped = cli._structured_errors("test")(fail)
    with pytest.raises(typer.Exit):
        wrapped()

    payload = json.loads(capsys.readouterr().err)
    assert payload == {
        "error_type": "ValueError",
        "event": "command_failed",
        "level": "error",
        "message": "safe failure",
        "operation": "test",
    }
