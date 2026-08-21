# Security Policy

## Supported versions

This project is an early MVP. Security fixes are applied to the latest release and `main`.

## Report a vulnerability

Do not open a public issue for a suspected vulnerability or leaked credential. Use GitHub's
**Security → Report a vulnerability** private reporting flow. Include impact, reproduction steps,
affected revision, and a proposed mitigation if available. Maintainers will acknowledge a report
when practical; this volunteer project does not promise a response SLA.

If a real credential appears anywhere, revoke it first. Git history rewriting is not a substitute
for rotation.

## Operator checklist

- Use a service account shared only into the selected folder where possible.
- Keep Google JSON keys, OAuth tokens, embedding-provider keys, bearer tokens, SQLite files, model
  caches, and backups outside source control with restrictive filesystem permissions.
- Treat hosted embedding endpoints as data processors: extracted chunks leave the service during
  indexing and search queries leave it at retrieval time. Review provider retention, training,
  residency, and access policies. Use an evaluated local provider when data must stay on-host.
- Supply embedding secrets only through the environment variable named by
  `GDRIVE_RAG_EMBED_API_KEY_ENV`. Never put credentials in an embedding base URL.
- Do not bypass embedding fingerprint failures. Mixing providers, models, endpoints, or dimensions
  can silently corrupt retrieval; rebuild the generated index or select another database/profile.
- Use TLS and a trusted reverse proxy for remote access. Add network allowlists, rate limiting,
  identity-aware access or mTLS when appropriate.
- Generate at least 32 random bytes for every profile bearer token and rotate it periodically.
- Keep token values in environment variables; access-policy JSON contains only token variable names.
- Derive authorization from the authenticated token. Never trust a caller-supplied profile ID.
- Grant wildcard owner/function/PARA access only to an explicitly trusted orchestrator. Test that
  member profiles cannot retrieve another owner's private chunks before production use.
- Treat the database as confidential because it contains extracted text.
- Run the container as the included non-root user and scan pinned dependencies/images regularly.
- Review source citations and freshness; the evidence gate does not make retrieved content correct.
