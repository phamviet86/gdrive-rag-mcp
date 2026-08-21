from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from gdrive_rag_mcp.access import current_scope
from gdrive_rag_mcp.server import BearerAuthMiddleware, create_http_app, create_mcp_server


async def noop_app(scope: object, receive: object, send: object) -> None:
    raise AssertionError("Unauthenticated requests must not reach the application")


def test_bearer_token_must_be_long() -> None:
    with pytest.raises(ValueError, match="32"):
        create_http_app(object(), "short")  # type: ignore[arg-type]


@pytest.mark.anyio
async def test_bearer_middleware_rejects_missing_token() -> None:
    messages: list[dict[str, object]] = []

    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict[str, object]) -> None:
        messages.append(message)

    middleware = BearerAuthMiddleware(noop_app, "x" * 32)
    await middleware(
        {"type": "http", "method": "POST", "path": "/mcp", "headers": []},  # type: ignore[arg-type]
        receive,  # type: ignore[arg-type]
        send,  # type: ignore[arg-type]
    )
    assert messages[0]["status"] == 401


@pytest.mark.anyio
async def test_bearer_middleware_binds_authenticated_profile_scope() -> None:
    observed: list[str] = []

    async def app(scope: object, receive: object, send: object) -> None:
        observed.append(current_scope().profile_id)

    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict[str, object]) -> None:
        pass

    token = "x" * 32
    middleware = BearerAuthMiddleware(app, token)  # type: ignore[arg-type]
    await middleware(
        {
            "type": "http",
            "method": "POST",
            "path": "/mcp",
            "headers": [(b"authorization", f"Bearer {token}".encode())],
        },  # type: ignore[arg-type]
        receive,  # type: ignore[arg-type]
        send,  # type: ignore[arg-type]
    )

    assert observed == ["legacy-http"]


def test_sample_configuration_contains_placeholders_only() -> None:
    sample = Path(".env.example").read_text(encoding="utf-8")
    assert "gho_" not in sample
    assert "AIza" not in sample
    assert "/Users/" not in sample
    assert "your_gemini_api_key" in sample
    assert "your_embedding_api_key" in sample
    ignore = Path(".gitignore").read_text(encoding="utf-8")
    for pattern in (
        ".env",
        "token*.json",
        "service-account*.json",
        "secrets/",
        "access-policy.json",
        "*.db",
    ):
        assert pattern in ignore
    policy = Path("access-policy.example.json").read_text(encoding="utf-8")
    assert "token_env" in policy
    assert "Bearer " not in policy


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
