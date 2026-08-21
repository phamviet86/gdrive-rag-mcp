from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from google_drive_rag_mcp import cli
from google_drive_rag_mcp.drive import _validate_client_secret_file
from google_drive_rag_mcp.server import create_mcp_server


def test_sample_configuration_contains_placeholders_only() -> None:
    sample = Path(".env.example").read_text(encoding="utf-8")
    assert "gho_" not in sample
    assert "AIza" not in sample
    assert "/Users/" not in sample
    assert "your_gemini_api_key" in sample
    assert "your_embedding_api_key" in sample
    assert "google-drive-rag-mcp-auth --client-secret" in sample
    ignore = Path(".gitignore").read_text(encoding="utf-8")
    for pattern in (
        ".env",
        "token*.json",
        "secrets/",
        "*.db",
    ):
        assert pattern in ignore


def test_client_secret_requires_desktop_installed_shape(tmp_path: Path) -> None:
    valid = tmp_path / "client_secret.json"
    valid.write_text(
        '{"installed":{"client_id":"example.apps.googleusercontent.com","client_secret":"secret"}}',
        encoding="utf-8",
    )
    _validate_client_secret_file(valid)

    for payload in (
        '{"web":{"client_id":"example","client_secret":"secret"}}',
        '{"unexpected":{"client_id":"example","client_secret":"secret"}}',
    ):
        invalid = tmp_path / "invalid.json"
        invalid.write_text(payload, encoding="utf-8")
        with pytest.raises(ValueError, match="OAuth Desktop"):
            _validate_client_secret_file(invalid)


def test_serve_always_uses_stdio(monkeypatch: pytest.MonkeyPatch) -> None:
    observed: list[str] = []
    settings = object()

    class FakeService:
        def __init__(self, configured_settings: object) -> None:
            assert configured_settings is settings

        def require_index_ready(self) -> None:
            observed.append("ready")

    class FakeServer:
        def run(self, *, transport: str) -> None:
            observed.append(transport)

    monkeypatch.setattr(cli.Settings, "from_env", lambda: settings)
    monkeypatch.setattr(cli, "KnowledgeService", FakeService)
    monkeypatch.setattr(cli, "create_mcp_server", lambda service: FakeServer())

    cli.serve()

    assert observed == ["ready", "stdio"]


def test_default_command_runs_stdio_server(monkeypatch: pytest.MonkeyPatch) -> None:
    observed: list[bool] = []
    monkeypatch.setattr(cli, "serve", lambda: observed.append(True))

    cli.main(SimpleNamespace(invoked_subcommand=None))  # type: ignore[arg-type]

    assert observed == [True]


@pytest.mark.anyio
async def test_mcp_tools_have_stable_names_and_read_only_annotations() -> None:
    service = SimpleNamespace(store=object(), retriever=object())
    tools = await create_mcp_server(service).list_tools()  # type: ignore[arg-type]
    assert {tool.name for tool in tools} == {
        "search_knowledge",
        "get_document",
        "get_document_metadata",
        "check_index_status",
    }
    assert all(tool.annotations and tool.annotations.read_only_hint for tool in tools)
    search_tool = next(tool for tool in tools if tool.name == "search_knowledge")
    assert {"query", "scope_id"} <= set(search_tool.input_schema["required"])
    for name in ("get_document", "get_document_metadata"):
        tool = next(item for item in tools if item.name == name)
        assert "file_id" in tool.input_schema["required"]
