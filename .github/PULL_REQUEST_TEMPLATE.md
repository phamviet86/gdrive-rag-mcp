## Summary

Describe the problem and the approach taken.

## Verification

List the commands or manual MCP checks you ran. Use fake sources and sanitized data; never attach
OAuth tokens, API keys, client secrets, private Drive IDs/links, document content, or production
database rows.

## Checklist

- [ ] The change is focused and preserves unrelated behavior.
- [ ] `uv run ruff format --check .` passes.
- [ ] `uv run ruff check .` passes.
- [ ] `uv run mypy src/google_drive_rag_mcp` passes.
- [ ] `uv run pytest` passes.
- [ ] Tests cover new behavior or the reason they are unnecessary is explained.
- [ ] README and community documentation are updated when contracts or setup change.
- [ ] SQLite schema, embedding identity, reindex, and migration impact are documented where relevant.
- [ ] The local-first `SentenceSplitter` + SQLite architecture remains explicit; no LlamaCloud dependency was added.
- [ ] No credentials, private Drive data, generated indexes, or sensitive logs are included.
- [ ] Security-sensitive findings were reported privately according to `SECURITY.md`.
