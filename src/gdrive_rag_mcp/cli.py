from __future__ import annotations

import json
import time
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
    store = SQLiteStore(settings.db_path, settings.embed_dimensions, settings.embedding_identity())
    typer.echo(json.dumps(store.status(), indent=2))


@app.command()
def sync(
    full: Annotated[
        bool,
        typer.Option("--full", help="Force a complete tree reconciliation."),
    ] = False,
) -> None:
    """Incrementally synchronize the configured Drive scope."""
    service = KnowledgeService(Settings.from_env())
    result = service.full_sync() if full else service.sync()
    typer.echo(json.dumps(result, indent=2))


@app.command("sync-loop")
def sync_loop(
    interval_seconds: Annotated[int, typer.Option(min=30)] = 300,
    full_interval_seconds: Annotated[int, typer.Option(min=300)] = 86400,
) -> None:
    """Poll Drive changes and periodically run a full reconciliation."""
    if full_interval_seconds < interval_seconds:
        raise typer.BadParameter("full interval must be greater than or equal to poll interval")
    service = KnowledgeService(Settings.from_env())
    last_full = 0.0
    while True:
        now = time.monotonic()
        if now - last_full >= full_interval_seconds:
            result = service.full_sync()
            last_full = now
        else:
            result = service.sync()
        typer.echo(json.dumps(result))
        time.sleep(interval_seconds)


@app.command()
def status() -> None:
    """Show index counts and freshness without external API calls."""
    settings = Settings.from_env()
    store = SQLiteStore(settings.db_path, settings.embed_dimensions, settings.embedding_identity())
    typer.echo(json.dumps(store.status(), indent=2))


@app.command()
def reindex(
    yes: Annotated[
        bool,
        typer.Option("--yes", help="Confirm deletion and full rebuild of generated index data."),
    ] = False,
) -> None:
    """Delete the selected generated index and rebuild it with the configured embedder."""
    if not yes:
        raise typer.BadParameter("Reindex deletes generated index data; rerun with --yes")
    settings = Settings.from_env()
    settings.require_sync()
    store = SQLiteStore(
        settings.db_path,
        settings.embed_dimensions,
        settings.embedding_identity(),
        enforce_identity=False,
    )
    store.reset_index(settings.embedding_identity())
    service = KnowledgeService(settings)
    typer.echo(json.dumps(service.sync(), indent=2))


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
    service.require_index_ready()
    if transport is Transport.stdio:
        create_mcp_server(service).run(transport="stdio")
        return
    http_app = create_http_app(service, settings.bearer_token)
    uvicorn.run(http_app, host=settings.host, port=settings.port)


if __name__ == "__main__":
    app()
