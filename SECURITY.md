# Security Policy

## Supported versions

Security fixes are provided for the current minor release line.

| Version | Supported |
| --- | --- |
| `0.5.x` | Yes |
| `< 0.5` | No |

Security fixes are developed on `main`, which may also contain other unreleased changes; `main` is
not a substitute for a supported release.

## Report a vulnerability

Do not open a public issue for a suspected vulnerability or leaked credential. Use GitHub's
[private vulnerability reporting form](https://github.com/phamviet86/google-drive-rag-mcp/security/advisories/new).
If private vulnerability reporting is unavailable, use a private contact method published on the
[repository owner's GitHub profile](https://github.com/phamviet86).
Include the affected revision, impact, synthetic reproduction steps, and a proposed mitigation if
available. Do not attach OAuth tokens, API keys, client secrets, private Drive URLs or IDs, document
content, production databases, or unsanitized logs—even in a private report. Redact private paths
and use minimal fake data that demonstrates the issue.

Maintainers will investigate privately, coordinate remediation and disclosure when practical, and
credit reporters who request it. This volunteer project does not promise a response or remediation
SLA. Do not publicly disclose an unpatched issue before maintainers have had a reasonable
opportunity to assess it.

If a real credential appears anywhere, revoke or rotate it first and remove public access to the
artifact. Git history rewriting is not a substitute for rotation. If private Drive content is
exposed, follow the data owner's incident-response process in addition to notifying maintainers.

## Operator checklist

- Use only a protected Google OAuth Desktop `client_secret.json` containing the top-level
  `installed` object.
- Keep the OAuth client file, OAuth tokens, embedding-provider keys, SQLite files, model
  caches, and backups outside source control with restrictive filesystem permissions.
- OAuth credentials must include a refresh token. Token creation and refresh are persisted with an
  atomic replace and mode `0600`; on POSIX systems the containing directory is also normalized to
  mode `0700`, and authentication fails closed if that permission cannot be applied.
- Treat hosted embedding endpoints as data processors: extracted chunks leave the service during
  indexing and search queries leave it at retrieval time. Review provider retention, training,
  residency, and access policies. Use an evaluated local provider when data must stay on-host.
- Supply embedding secrets only through the environment variable named by
  `GOOGLE_DRIVE_RAG_EMBED_API_KEY_ENV`. Never put credentials in an embedding base URL.
- Do not bypass embedding fingerprint failures. Mixing providers, models, endpoints, or dimensions
  can silently corrupt retrieval; rebuild the generated index or select another database path.
- Do not convert generic `403` responses into deletions. Only Drive `change.removed` or
  `404/notFound` permits immediate incremental deletion; quota, backend, and permission failures
  must exhaust native retries and then fail closed. Likewise, never use an `incompleteSearch` list
  response for authoritative cleanup.
- Run the stdio server only from trusted local MCP clients and restrict access to its configuration,
  environment, database, and executable.
- Treat every document below `GOOGLE_DRIVE_FOLDER_ID` as searchable by every authorized client. Use a
  separate service and index root if a corpus requires a different security boundary.
- Treat the database as confidential because it contains extracted text.
- Run the local process as an unprivileged user and scan pinned dependencies regularly.
- Review source citations and freshness; the evidence gate does not make retrieved content correct.
