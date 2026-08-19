from __future__ import annotations

import json
from enum import StrEnum
from typing import Annotated

import typer
import uvicorn

from .config import Settings
from .drive import run_oauth
from .server import create_http_app, create_mcp_server
from .service import KnowledgeService
from .storage import SQLiteStore

app = typer.Typer(no_args_is_help=True, help="Google Drive hybrid retrieval MCP server")


class Transport(StrEnum):
    stdio = "stdio"
    http = "http"


@app.command("init-db")
def init_db() -> None:
    """Initialize or migrate the SQLite index."""
    settings = Settings.from_env()
    store = SQLiteStore(settings.db_path, settings.embed_dimensions)
    typer.echo(json.dumps(store.status(), indent=2))


@app.command()
def sync() -> None:
    """Incrementally synchronize the configured Drive scope."""
    service = KnowledgeService(Settings.from_env())
    typer.echo(json.dumps(service.sync(), indent=2))


@app.command()
def status() -> None:
    """Show index counts and freshness without external API calls."""
    settings = Settings.from_env()
    store = SQLiteStore(settings.db_path, settings.embed_dimensions)
    typer.echo(json.dumps(store.status(), indent=2))


@app.command("auth-google")
def auth_google() -> None:
    """Run installed-app OAuth and store the refresh token at the configured ignored path."""
    path = run_oauth(Settings.from_env())
    typer.echo(f"OAuth token stored with user-only permissions at {path}")


@app.command()
def serve(
    transport: Annotated[Transport, typer.Option(case_sensitive=False)] = Transport.stdio,
) -> None:
    """Run MCP over local stdio or authenticated Streamable HTTP."""
    settings = Settings.from_env()
    service = KnowledgeService(settings)
    if transport is Transport.stdio:
        create_mcp_server(service).run(transport="stdio")
        return
    http_app = create_http_app(service, settings.bearer_token)
    uvicorn.run(http_app, host=settings.host, port=settings.port)


if __name__ == "__main__":
    app()
