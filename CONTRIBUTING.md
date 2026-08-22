# Contributing to Google Drive RAG MCP

Thank you for improving Google Drive RAG MCP. This is a local-first, read-only retrieval service:
Google Drive is the source of truth, LlamaIndex `SentenceSplitter` is the replaceable chunking
boundary, and SQLite provides the durable FTS5/vector hybrid index. Contributions must preserve
that boundary unless a proposal explicitly discusses a larger architectural change. The project
does not use LlamaCloud.

By participating, you agree to the [Code of Conduct](CODE_OF_CONDUCT.md). Report suspected
vulnerabilities privately as described in the [Security Policy](SECURITY.md), not in an issue or
pull request.

## Before opening a change

- Search existing issues and documentation first.
- Open a feature request before a substantial API, schema, authentication, indexing, or MCP tool
  change so compatibility and security can be discussed.
- Keep pull requests focused. Do not combine unrelated formatting or dependency updates.
- Never use real OAuth tokens, API keys, client secrets, Drive IDs/links, document names/content,
  production database rows, or private filesystem paths in tests, logs, screenshots, issues, or
  commits. Revoke an exposed credential immediately.

## Development setup

CI tests Python 3.11 through 3.14, matching the versions declared in `pyproject.toml`. From a fork
or local clone:

```bash
git clone https://github.com/YOUR-USER/google-drive-rag-mcp.git
cd google-drive-rag-mcp
uv sync --locked --extra dev
```

Resolve the optional Sentence Transformers environment without installing its heavy runtime with
`uv sync --locked --extra dev --extra sentence-transformers --dry-run`; install that extra only when
changing the adapter. The normal test suite does not download a model and requires no Google,
Gemini, OpenAI, or other external credentials. If dependency declarations change, run `uv lock`
and commit the updated `uv.lock`.
Create a focused branch from an up-to-date `main`; keep unrelated refactors out of the same pull
request.

## Tests and quality checks

Run the same checks as CI:

```bash
uv run ruff format --check .
uv run ruff check .
uv run mypy src/google_drive_rag_mcp
uv run pytest
uv run google-drive-rag-mcp --help
uv run google-drive-rag-mcp auth-google --help
uv run google-drive-rag-mcp-auth --help
```

Use `uv run ruff format .` to apply formatting. Add the narrowest regression test that fails before
the change and passes after it.

Drive and OAuth tests must use fake discovery resources, fake requests, synthetic `HttpError`
payloads, and temporary token paths. MCP tests should construct the in-process server with
`create_mcp_server` and inspect or call its tools without starting a network listener or using a
real MCP client account. Embedding tests should use deterministic fakes or `httpx.MockTransport`.

When changing synchronization behavior, cover retries, pagination, incomplete searches,
`change.removed`, `404/notFound`, non-deletion errors, download capability, and resource cleanup as
applicable. A partial or ambiguous Drive result must never authorize destructive index cleanup.

## Architecture and compatibility checks

Changes to extraction, chunking, embedding providers, ranking, authentication, storage, or data
retention should explain:

- whether data leaves the local machine and which processor receives it;
- OAuth scope and token-storage implications;
- SQLite schema, embedding fingerprint, reindex, backup, and migration impact;
- MCP tool contract or client-configuration changes;
- failure behavior, retries, structured stderr output, and resource lifecycle;
- quality limitations and the credential-free tests used to evaluate the change.

Keep provider-specific SDKs optional unless they are part of the documented base install. Do not
add LlamaCloud or another hosted index as an implicit dependency. Do not weaken the shared-index
root check, embedding identity check, evidence gate, or fail-closed deletion rules.

Update `README.md` and `.env.example` whenever a change affects installation, CLI arguments,
environment variables, defaults, OAuth, sync/index behavior, MCP tool schemas, deployment examples,
or troubleshooting. Keep `pyproject.toml`, `src/google_drive_rag_mcp/`, tests, and user-facing docs
consistent.

## Pull requests

A pull request should include a concise summary, relevant issue, user-visible limitations,
migration or reindex instructions, documentation changes, and exact validation performed. CI must
pass on every supported matrix version. Maintainers may request a smaller change or additional
security/quality evidence before review.
