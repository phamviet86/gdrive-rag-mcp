# Contributing

Thank you for improving google-drive-rag-mcp.

1. Open an issue for substantial changes so scope and security impact can be discussed.
2. Fork the repository and create a focused branch.
3. Never use real Drive data or credentials in fixtures, logs, screenshots, commits, or issues.
4. Add or update credential-free tests.
5. Run `ruff format --check .`, `ruff check .`, `mypy src/google_drive_rag_mcp`, and `pytest`.
6. Open a pull request describing behavior, limitations, migration impact, and validation.

Changes to extraction, embedding providers, ranking, authentication, or data retention should
include threat/quality considerations, offline tests, and an explicit index-migration assessment.
Keep heavyweight provider SDKs optional. By participating, you agree to
[CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).
