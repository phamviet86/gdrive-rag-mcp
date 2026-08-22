from __future__ import annotations

import json
import time
from collections.abc import Callable
from functools import wraps
from pathlib import Path
from typing import Annotated, ParamSpec, TypeVar

import typer

from .config import Settings
from .drive import run_oauth
from .logging_utils import emit_stderr
from .server import create_mcp_server
from .service import KnowledgeService
from .storage import SQLiteStore

app = typer.Typer(
    invoke_without_command=True,
    help="Google Drive hybrid retrieval MCP server",
)

P = ParamSpec("P")
R = TypeVar("R")


def _structured_errors(operation: str) -> Callable[[Callable[P, R]], Callable[P, R]]:
    def decorator(function: Callable[P, R]) -> Callable[P, R]:
        @wraps(function)
        def wrapped(*args: P.args, **kwargs: P.kwargs) -> R:
            try:
                return function(*args, **kwargs)
            except (typer.Exit, typer.BadParameter):
                raise
            except Exception as error:
                emit_stderr(
                    "command_failed",
                    operation=operation,
                    error_type=type(error).__name__,
                    message=str(error),
                )
                raise typer.Exit(code=1) from error

        return wrapped

    return decorator


@app.callback()
def main(ctx: typer.Context) -> None:
    """Run the stdio server by default; use a subcommand for index maintenance."""
    if ctx.invoked_subcommand is None:
        serve()


@app.command("init-db")
@_structured_errors("init-db")
def init_db() -> None:
    """Initialize or migrate the SQLite index."""
    settings = Settings.from_env()
    store = SQLiteStore(settings.db_path, settings.embed_dimensions, settings.embedding_identity())
    typer.echo(json.dumps(store.status(), indent=2))


@app.command()
@_structured_errors("sync")
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
@_structured_errors("sync-loop")
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
@_structured_errors("status")
def status() -> None:
    """Show index counts and freshness without external API calls."""
    settings = Settings.from_env()
    store = SQLiteStore(settings.db_path, settings.embed_dimensions, settings.embedding_identity())
    typer.echo(json.dumps(store.status(), indent=2))


@app.command()
@_structured_errors("reindex")
def reindex(
    yes: Annotated[
        bool,
        typer.Option("--yes", help="Confirm deletion and full rebuild of generated index data."),
    ] = False,
) -> None:
    """Delete the shared generated index and rebuild it with the configured embedder."""
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
@_structured_errors("auth-google")
def auth_google(
    client_secret: Annotated[
        Path,
        typer.Option(
            "--client-secret",
            exists=True,
            file_okay=True,
            dir_okay=False,
            readable=True,
            resolve_path=True,
            help="Google OAuth Desktop client_secret.json file.",
        ),
    ],
) -> None:
    """Run installed-app OAuth and store the refresh token at the configured ignored path."""
    try:
        path = run_oauth(Settings.from_env(), client_secret)
    except ValueError as error:
        emit_stderr(
            "command_failed",
            operation="auth-google",
            error_type=type(error).__name__,
            message=str(error),
        )
        raise typer.BadParameter(str(error), param_hint="--client-secret") from error
    typer.echo(f"OAuth token stored with user-only permissions at {path}")


def auth_google_cli() -> None:
    """Expose the same authentication syntax through the dedicated console command."""
    typer.run(auth_google)


@app.command()
@_structured_errors("serve")
def serve() -> None:
    """Run the local MCP server over stdio."""
    settings = Settings.from_env()
    service = KnowledgeService(settings)
    service.require_index_ready()
    typer.echo("google-drive-rag-mcp running on stdio", err=True)
    create_mcp_server(service).run(transport="stdio")


if __name__ == "__main__":
    app()
