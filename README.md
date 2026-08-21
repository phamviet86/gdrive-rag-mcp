# google-drive-rag-mcp

[![CI](https://github.com/phamviet86/google-drive-rag-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/phamviet86/google-drive-rag-mcp/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

A local-first Google Drive hybrid index exposed to local MCP clients over stdio.
Choose an embedding provider and model that fit your languages, privacy boundary, and
infrastructure; then let every Hermes profile or other MCP client query the same durable index.

Google Drive/Workspace remains the read-only source of truth. The service stores extracted chunks,
normalized embeddings, metadata, checksums, sync state, and index data—not downloaded source files.
It requires no LlamaCloud and uses LlamaIndex only at the replaceable chunking boundary.

> **Important:** retrieval assists research; it is not legal, tax, financial, economic, or business
> advice. Agents and people must inspect the linked source, effective date, jurisdiction, and later
> amendments. If `evidence.sufficient` is false, abstain instead of filling gaps.

## What the MVP does

- Recursively reads one configured Drive folder or Shared Drive scope with the read-only API.
- Stores every ancestor folder ID so any folder can be used as a recursive search boundary.
- Stores the relative Drive path for readable citations without deriving profile-specific scopes.
- Filters both FTS5 and vector candidates by a caller-supplied Drive folder or file ID before
  ranking.
- Extracts Google Docs, Google Sheets, text/Markdown, text-based PDFs, and DOCX.
- Supports Gemini, any verified OpenAI-compatible `/embeddings` endpoint, and optional local
  Sentence Transformers behind one embedding protocol.
- Combines Unicode-safe SQLite FTS5 keyword search with sqlite-vec cosine search. A tested Python
  cosine fallback is used when the extension cannot load.
- Uses the Drive Changes API after an initial full scan, removes deleted/out-of-scope files, and
  periodically supports a complete reconciliation for moves and manually added content.
- Prevents vectors from different providers, models, endpoints, or dimensions from sharing an
  index by recording and validating an embedding fingerprint.
- Returns citations, source modified/indexed times, and a conservative evidence decision.
- Exposes shared read-only tools over stdio, with no listening network port.

## Architecture

```mermaid
flowchart LR
    D[Selected Google Drive root] -->|read-only Drive API + change feed| X[Folder ancestry]
    X -->|folder IDs + optional path labels| Y[Format extractors]
    Y --> L[LlamaIndex chunking boundary]
    L --> E{Embedding provider}
    E -->|Gemini| V[Normalized vectors]
    E -->|OpenAI-compatible HTTP| V
    E -->|Local Sentence Transformers| V
    L --> S[(SQLite documents + FTS5)]
    V --> Q[(sqlite-vec / cosine fallback)]
    S --> R[Folder or file ID pre-filter]
    Q --> R
    R --> H[Hybrid ranking + evidence gate]
    H --> M[Agent-neutral MCP tools]
    M --> A[Any compatible MCP client]
```

Google and embedding-provider credentials stay in the local environment inherited by the indexing
commands and MCP subprocess. The MCP client starts and communicates with the server over stdio.

## Embedding providers

Language coverage is a property of the selected model, not an indexing “language mode.” FTS5 uses
SQLite's Unicode tokenizer, while semantic quality depends on the model and domain. Evaluate your
actual languages and documents; this project does not claim perfect support for every language.

| Provider | Execution/privacy | Multilingual suitability | Extra install | Notes |
|---|---|---|---|---|
| `gemini` (default) | Hosted; chunks and queries go to Google's embedding API | Model-dependent; the default is designed for multilingual retrieval | None | Default provider/model/dimension configuration |
| `openai-compatible` | Hosted or self-hosted; data goes to the configured base URL | Model-dependent | None | Implements the documented `POST /embeddings` JSON contract; API key may be optional for a trusted local endpoint |
| `sentence-transformers` | Local process/device after model download | Choose and evaluate a multilingual retrieval model | `pip install 'google-drive-rag-mcp[sentence-transformers]'` | Heavy PyTorch/model dependencies stay out of the base install |

Changing the embedding provider, model, endpoint, or dimensions requires rebuilding that vector
index. Changing MCP clients or agents does **not** require reindexing.

The HTTP adapter follows the [official OpenAI embeddings request/response schema](https://platform.openai.com/docs/api-reference/embeddings/create),
including batched string input, ordered results, optional dimensions, and float vectors. A dedicated
Ollama adapter is not claimed. If a particular Ollama deployment explicitly implements that
`/v1/embeddings` contract, test it as an OpenAI-compatible endpoint and set
`GOOGLE_DRIVE_RAG_EMBED_SEND_DIMENSIONS=false` if that deployment does not accept the dimensions field.

Gemini uses retrieval-specific query/document tasks and explicit output dimensions described in
the [official Gemini embedding documentation](https://ai.google.dev/gemini-api/docs/embeddings).
The local adapter uses the documented Sentence Transformers
[`encode_query` and `encode_document`](https://www.sbert.net/docs/package_reference/sentence_transformer/model.html)
methods with normalized output.

## Install

```bash
git clone https://github.com/phamviet86/google-drive-rag-mcp.git
cd google-drive-rag-mcp
python3.12 -m venv .venv
. .venv/bin/activate
pip install -e .
cp .env.example .env
```

For the local provider, install `pip install -e '.[sentence-transformers]'` instead. The project does
not automatically parse `.env`; load it with your shell or process manager. For example,
`set -a; . ./.env; set +a` in a trusted interactive shell. Never commit `.env`.

## Configure an embedding provider

Secret values come from the environment variable named by
`GOOGLE_DRIVE_RAG_EMBED_API_KEY_ENV`. The variable name is configuration; the secret value is never
stored in the index fingerprint or sample files.

### Gemini (default)

If provider settings are absent, the service uses Gemini, `gemini-embedding-001`, 768 dimensions,
and `GEMINI_API_KEY`.

```bash
export GOOGLE_DRIVE_RAG_EMBED_PROVIDER=gemini
export GOOGLE_DRIVE_RAG_EMBED_MODEL=gemini-embedding-001
export GOOGLE_DRIVE_RAG_EMBED_DIMENSIONS=768
export GOOGLE_DRIVE_RAG_EMBED_API_KEY_ENV=GEMINI_API_KEY
export GEMINI_API_KEY=your_runtime_secret
```

### OpenAI-compatible endpoint

```bash
export GOOGLE_DRIVE_RAG_EMBED_PROVIDER=openai-compatible
export GOOGLE_DRIVE_RAG_EMBED_MODEL=text-embedding-3-small
export GOOGLE_DRIVE_RAG_EMBED_DIMENSIONS=1536
export GOOGLE_DRIVE_RAG_EMBED_BASE_URL=https://api.openai.com/v1
export GOOGLE_DRIVE_RAG_EMBED_API_KEY_ENV=OPENAI_API_KEY
export OPENAI_API_KEY=your_runtime_secret
```

For another compatible endpoint, replace the base URL, model, dimensions, and key variable. Never
put credentials in the base URL. Set `GOOGLE_DRIVE_RAG_EMBED_SEND_DIMENSIONS=false` only when the verified
endpoint/model does not accept that optional field; the configured output dimension is still
validated on every response.

OpenRouter exposes the same `/embeddings` contract. This example uses Qwen3 Embedding 8B at its
full 4096 dimensions and sends distinct query/document input types:

```bash
export GOOGLE_DRIVE_RAG_EMBED_PROVIDER=openai-compatible
export GOOGLE_DRIVE_RAG_EMBED_MODEL=qwen/qwen3-embedding-8b
export GOOGLE_DRIVE_RAG_EMBED_DIMENSIONS=4096
export GOOGLE_DRIVE_RAG_EMBED_BASE_URL=https://openrouter.ai/api/v1
export GOOGLE_DRIVE_RAG_EMBED_API_KEY_ENV=OPENROUTER_API_KEY
export OPENROUTER_API_KEY=your_runtime_secret
export GOOGLE_DRIVE_RAG_EMBED_QUERY_INPUT_TYPE=search_query
export GOOGLE_DRIVE_RAG_EMBED_DOCUMENT_INPUT_TYPE=search_document
```

Free OpenRouter endpoints may log or retain inputs. Do not send confidential Drive content to a
free endpoint unless its current data policy has been reviewed and explicitly accepted. Use a
suitable paid route with data collection denied or a local Sentence Transformers model when the
corpus must remain private.

### Local Sentence Transformers

```bash
pip install -e '.[sentence-transformers]'
export GOOGLE_DRIVE_RAG_EMBED_PROVIDER=sentence-transformers
export GOOGLE_DRIVE_RAG_EMBED_MODEL=sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2
export GOOGLE_DRIVE_RAG_EMBED_DIMENSIONS=384
export GOOGLE_DRIVE_RAG_EMBED_DEVICE=cpu  # or a device supported by your local installation
```

The model name above is an example, not a universal recommendation. Model download/cache behavior,
licenses, language coverage, memory use, and hardware requirements belong to the selected model.

Common tuning:

```bash
export GOOGLE_DRIVE_RAG_EMBED_BATCH_SIZE=32
export GOOGLE_DRIVE_RAG_EMBED_TIMEOUT_SECONDS=60
```

All providers return normalized vectors and must return exactly the configured dimensions.

## Google authentication

Enable the Google Drive API and create an OAuth client with application type **Desktop app**.
Download its `client_secret.json`, keep it protected outside the repository, and provide it when
authorizing this project. The project accepts only the Desktop client JSON shape with a top-level
`installed` object.

Authenticate with:

```bash
google-drive-rag-mcp-auth --client-secret /secure/google/client_secret.json
```

The JSON must contain the top-level `installed` object. The browser flow requests only
`https://www.googleapis.com/auth/drive.readonly` and stores the resulting refresh token at
`~/.config/google-drive-rag-mcp/token.json` with owner-only permissions. Later Drive syncs use this
stored token and refresh access automatically. Set `GOOGLE_TOKEN_FILE` only when the generated token
must be stored at a different path. Keep both the client JSON and generated token outside the
repository and never commit them.

The Drive API has no OAuth scope meaning “read only this existing folder.” The OAuth token can read
files the user can read; the indexer enforces the configured folder during traversal. See Google's
[Drive authorization guide](https://developers.google.com/workspace/drive/api/guides/api-specific-auth).

## Drive folder scopes

`GOOGLE_DRIVE_FOLDER_ID` is the root indexed by the worker. The folder layout is an organizational
choice, not an authorization schema. A profile/business/PARA structure remains useful, for example:

```text
<configured-root>/
└── <owner-profile-id>/
    └── <business-function>/
        ├── projects/
        ├── areas/
        ├── resources/
        └── archives/
```

Every supported file below the configured root is indexed regardless of depth. The index records
the configured root ID and every descendant folder ID in that file's ancestry. Therefore one
`scope_id` accepts either a Drive folder ID or an indexed file ID:

- a profile-owner folder ID searches the entire profile tree;
- a business-function folder ID searches that function and every nested PARA folder;
- any deeper folder ID narrows the same operation to that subtree.
- a file ID searches only that indexed file.

Folder names remain visible only through the relative path. There is no per-profile index, scope
configuration, access policy, or database. `GOOGLE_DRIVE_FOLDER_ID` alone defines the tree indexed by the
worker. IDs outside that indexed tree produce no search results. The server refuses to start if
the configured root differs from the root recorded by the last full sync.

## Build, refresh, and migrate an index

```bash
google-drive-rag-mcp init-db
google-drive-rag-mcp sync
google-drive-rag-mcp status
```

The first `sync` performs a full tree reconciliation and records a Drive start-page token. Later
runs consume the Drive Changes API, avoid re-embedding unchanged files, and remove deleted,
inaccessible, or moved-out files. A folder change triggers a full reconciliation because it can
change the ancestry of every descendant.

Run a durable polling worker on the VPS:

```bash
google-drive-rag-mcp sync-loop --interval-seconds 300 --full-interval-seconds 86400
```

The change feed provides frequent updates; the daily full pass reconciles manual additions and
scope/path changes. Operators can force one immediately with `google-drive-rag-mcp sync --full`.

### Embedding fingerprint and legacy indexes

Each database records provider, model, dimensions, endpoint identity, and a SHA-256 fingerprint.
The MCP status tool returns provider/model/dimensions/fingerprint but does not expose the endpoint.

Version 0.1.x databases did not record embedding identity. A non-empty legacy index cannot be
safely inferred—even if it probably used the old Gemini default—so version 0.2 refuses to open it.
Back up the database if desired, load the same Drive/provider credentials, then explicitly rebuild:

```bash
google-drive-rag-mcp reindex --yes
```

The command deletes only generated index data in the selected database and performs a full Drive
sync. It does not modify Drive. An empty legacy database is stamped automatically.

Version 0.3 added path classification columns to existing databases. Version 0.5 no longer uses
those legacy columns.

Version 0.4 replaces label-based authorization with recursive folder-ID ancestry. The schema
migrates automatically, but old rows have no ancestry entries. Run `google-drive-rag-mcp sync --full`
before serving so each document records the configured root and all parent folder IDs.

Version 0.5 makes the service and index shared across all clients, removes per-profile access
configuration, and accepts one folder-or-file `scope_id` per search. Existing 0.4 ancestry data is
compatible; no rebuild is required when it is already populated.

To keep multiple intentional indexes, use named profiles or explicit paths:

```bash
GOOGLE_DRIVE_RAG_INDEX_PROFILE=gemini google-drive-rag-mcp sync
GOOGLE_DRIVE_RAG_INDEX_PROFILE=local-multilingual google-drive-rag-mcp sync
# Or set GOOGLE_DRIVE_RAG_DB_PATH explicitly for complete path control.
```

The default index profile keeps the backward-compatible `data/index.db` path; other index profiles
derive `data/index-<profile>.db`. An index profile selects an embedding/database combination; it is
not a Hermes caller profile or an authorization boundary.

## MCP tools

All tool names and instructions are agent-neutral and marked read-only.

| Tool | Purpose |
|---|---|
| `search_knowledge(query, scope_id, limit)` | Search one indexed file ID, or one folder ID and all descendants, with citations and an evidence decision |
| `get_document(file_id)` | Resolve an indexed Drive ID and instruct the caller to read the current source through Google Workspace |
| `get_document_metadata(file_id)` | URL, relative path, ancestor folder IDs, checksum, and modified/indexed times |
| `check_index_status()` | Shared counts, last sync, vector backend, and embedding fingerprint |

Weak hits are placed in `candidate_results` for diagnostics; normal `results` remain empty when the
top score is below `GOOGLE_DRIVE_RAG_EVIDENCE_THRESHOLD`. Each hit returns its indexed `file_id` for a
current Google Workspace read.

Search returns indexed excerpts, not a second authoritative document. `get_document` deliberately
does not return reconstructed full cached text. Use its indexed Drive ID with Google Workspace
when the complete or current document is required.

## Run the MCP server over stdio

```bash
google-drive-rag-mcp
```

The command always uses stdio and does not open an HTTP port. The MCP client launches this process and
must make the database and embedding configuration available to it. Search needs provider access
for the query embedding; it does not need Google credentials unless the same environment also runs
sync commands.

### Hermes Agent local YAML

Hermes reads MCP servers from `~/.hermes/config.yaml` and supports environment substitution. Keep
actual secrets in `~/.hermes/.env` or the parent environment.

```yaml
mcp_servers:
  google_drive_rag:
    command: "/path/to/google-drive-rag-mcp/.venv/bin/google-drive-rag-mcp"
    args: []
    env:
      GOOGLE_DRIVE_RAG_DB_PATH: "${GOOGLE_DRIVE_RAG_DB_PATH}"
      GOOGLE_DRIVE_RAG_EMBED_PROVIDER: "${GOOGLE_DRIVE_RAG_EMBED_PROVIDER}"
      GOOGLE_DRIVE_RAG_EMBED_MODEL: "${GOOGLE_DRIVE_RAG_EMBED_MODEL}"
      GOOGLE_DRIVE_RAG_EMBED_DIMENSIONS: "${GOOGLE_DRIVE_RAG_EMBED_DIMENSIONS}"
      GOOGLE_DRIVE_RAG_EMBED_BASE_URL: "${GOOGLE_DRIVE_RAG_EMBED_BASE_URL}"
      GOOGLE_DRIVE_RAG_EMBED_API_KEY_ENV: "${GOOGLE_DRIVE_RAG_EMBED_API_KEY_ENV}"
      GEMINI_API_KEY: "${GEMINI_API_KEY}"
      OPENROUTER_API_KEY: "${OPENROUTER_API_KEY}"
    timeout: 120
    connect_timeout: 30
    supports_parallel_tool_calls: true
```

Replace the final secret variable with the one named by your provider configuration. The format is
based on the [official Hermes MCP guide](https://github.com/NousResearch/hermes-agent/blob/main/website/docs/user-guide/features/mcp.md).

### Codex local TOML

Add to `~/.codex/config.toml` or a trusted project `.codex/config.toml`:

```toml
[mcp_servers.google_drive_rag]
command = "/path/to/google-drive-rag-mcp/.venv/bin/google-drive-rag-mcp"
cwd = "/path/to/google-drive-rag-mcp"
env_vars = [
  "GOOGLE_DRIVE_RAG_DB_PATH",
  "GOOGLE_DRIVE_RAG_EMBED_PROVIDER",
  "GOOGLE_DRIVE_RAG_EMBED_MODEL",
  "GOOGLE_DRIVE_RAG_EMBED_DIMENSIONS",
  "GOOGLE_DRIVE_RAG_EMBED_BASE_URL",
  "GOOGLE_DRIVE_RAG_EMBED_API_KEY_ENV",
  "GEMINI_API_KEY",
  "OPENAI_API_KEY",
  "OPENROUTER_API_KEY",
]
startup_timeout_sec = 30
tool_timeout_sec = 120
required = true
```

Codex's current stdio configuration is documented in the
[official Codex MCP guide](https://developers.openai.com/codex/mcp).

### Generic MCP client

MCP configuration syntax is client-specific. Configure a standards-compliant client with command
`google-drive-rag-mcp`, no arguments, a working directory containing the index (or an explicit
`GOOGLE_DRIVE_RAG_DB_PATH`), and the embedding environment.

The server does not expose Google or embedding-provider credentials to the client. For OpenClaw or
another agent without a verified native format here, configure its standards-compliant MCP adapter
with those transport values rather than copying an unverified client-specific snippet.

## Security and data handling

- `.env`, databases, OAuth tokens, client secrets, downloaded files, model
  caches, and generated indexes must remain outside source control.
- SQLite contains extracted source text. Encrypt disks/backups and restrict OS/volume access.
- Hosted embedding providers receive extracted chunks during sync and queries during search. Review
  their data terms and residency. Use a suitable local model when data must not leave the host.
- API-key values come only from environment variables. Base URLs containing credentials are rejected.
- The fingerprint stores a provider/model/dimension/endpoint identity, never an API key. MCP status
  omits the endpoint.
- Rotate Google and embedding-provider credentials and restart after rotation.
- Restrict access to the local account and MCP client configuration. Any local client that can start
  the configured server can query every folder or file contained in its index root.
- Tools are retrieval-only; Drive writes and index mutation are not exposed through MCP.
- See [SECURITY.md](SECURITY.md) for reporting and deployment hardening.

## Honest limitations

- Scanned/image-only PDFs need OCR before indexing; this project does not perform OCR.
- Sheets index displayed cell values and sheet names, not charts, comments, or formula logic.
- Docs comments, suggestions, revision history, linked files, and rich layout are not preserved.
- Slides, images, audio, video, shortcuts, and arbitrary binary formats are skipped.
- The change feed is polling, not a push webhook. Freshness is bounded by the worker interval, and
  folder changes intentionally trigger a full reconciliation.
- The shared index does not replicate native per-file Drive ACLs or isolate Hermes profiles. Keep
  only documents intended for all tool users under `GOOGLE_DRIVE_FOLDER_ID` and retain Drive ACLs as the
  primary storage boundary.
- Search scores are heuristics, not probabilities. Tune the evidence threshold with domain-specific,
  multilingual evaluation before high-stakes use.
- FTS tokenization is Unicode-aware but not a language-specific morphological analyzer. Languages
  without whitespace or with complex segmentation may depend more heavily on semantic retrieval.
- SQLite suits a small shared service, not high-write or large distributed workloads. Persistence
  and retrieval remain isolated so they can be replaced later.

## Development

```bash
python3.12 -m venv .venv
. .venv/bin/activate
pip install -e '.[dev]'
ruff format --check .
ruff check .
mypy src/google_drive_rag_mcp
pytest
```

Tests use fake sources, HTTP transports, and deterministic Unicode-safe embeddings. They require no
Google, Gemini, OpenAI, or local model credentials. See [CONTRIBUTING.md](CONTRIBUTING.md).

## Khởi động nhanh bằng tiếng Việt

Đây là ví dụ cộng đồng; dự án không mặc định một ngôn ngữ. Chất lượng tìm kiếm ngữ nghĩa phụ thuộc
vào model embedding đã chọn.

1. Bật Google Drive API, tạo OAuth Desktop client và chạy
   `google-drive-rag-mcp-auth --client-secret /path/to/client_secret.json`.
2. Sao chép `.env.example` thành `.env`; cấu hình thư mục Drive, provider/model embedding và secret
   qua biến môi trường.
3. Chọn model có chất lượng tiếng Việt đã được bạn đánh giá, sau đó chạy `google-drive-rag-mcp sync`.
4. Chạy `google-drive-rag-mcp` qua stdio từ MCP client. Đổi agent không cần lập chỉ mục lại; đổi
   provider/model/dimensions thì chạy `google-drive-rag-mcp reindex --yes` hoặc dùng profile/database khác.
5. Khi `evidence.sufficient=false`, agent phải từ chối kết luận; luôn mở nguồn Drive, kiểm tra ngày
   hiệu lực và trích dẫn.

## License

[MIT](LICENSE)
