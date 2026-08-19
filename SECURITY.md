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
- Keep Google JSON keys, OAuth tokens, Gemini keys, bearer tokens, SQLite files, and backups outside
  source control with restrictive filesystem permissions.
- Use TLS and a trusted reverse proxy for remote access. Add network allowlists, rate limiting,
  identity-aware access or mTLS when appropriate.
- Generate at least 32 random bytes for the bearer token and rotate it periodically.
- Treat the database as confidential because it contains extracted text.
- Run the container as the included non-root user and scan pinned dependencies/images regularly.
- Review source citations and freshness; the evidence gate does not make retrieved content correct.
