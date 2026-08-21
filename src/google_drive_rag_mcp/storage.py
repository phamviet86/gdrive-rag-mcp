from __future__ import annotations

import json
import math
import sqlite3
from array import array
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .embeddings import EmbeddingIdentity
from .models import DocumentMetadata, SearchHit, SourceDocument


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _pack(values: Sequence[float]) -> bytes:
    return array("f", values).tobytes()


def _unpack(value: bytes) -> list[float]:
    result = array("f")
    result.frombytes(value)
    return list(result)


class ReindexRequiredError(RuntimeError):
    """Raised when configured embeddings cannot safely share the existing index."""


class SQLiteStore:
    def __init__(
        self,
        path: Path,
        dimensions: int,
        embedding_identity: EmbeddingIdentity | None = None,
        *,
        enforce_identity: bool = True,
    ) -> None:
        self.path = path
        self.dimensions = dimensions
        self.embedding_identity = embedding_identity
        self.enforce_identity = enforce_identity
        self.vector_extension = False
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()
        self.path.chmod(0o600)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA journal_mode=WAL")
        try:
            import sqlite_vec

            connection.enable_load_extension(True)
            sqlite_vec.load(connection)
            connection.enable_load_extension(False)
            self.vector_extension = True
        except (ImportError, sqlite3.Error):
            self.vector_extension = False
        return connection

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            yield connection
        finally:
            connection.close()

    def initialize(self) -> None:
        with self.connection() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS documents (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    mime_type TEXT NOT NULL,
                    modified_time TEXT NOT NULL,
                    checksum TEXT NOT NULL,
                    web_url TEXT NOT NULL,
                    indexed_at TEXT NOT NULL,
                    relative_path TEXT NOT NULL DEFAULT '',
                    parent_folder_id TEXT NOT NULL DEFAULT '',
                    folder_ancestry TEXT NOT NULL DEFAULT '[]'
                );
                CREATE TABLE IF NOT EXISTS document_folder_ancestors (
                    document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
                    folder_id TEXT NOT NULL,
                    depth INTEGER NOT NULL,
                    PRIMARY KEY(document_id, folder_id)
                );
                CREATE INDEX IF NOT EXISTS idx_document_folder_ancestors_folder
                    ON document_folder_ancestors(folder_id, document_id);
                CREATE TABLE IF NOT EXISTS chunks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
                    position INTEGER NOT NULL,
                    text TEXT NOT NULL,
                    embedding BLOB NOT NULL,
                    UNIQUE(document_id, position)
                );
                CREATE INDEX IF NOT EXISTS idx_chunks_document ON chunks(document_id);
                CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
                    chunk_id UNINDEXED, text, tokenize='unicode61 remove_diacritics 2'
                );
                CREATE TABLE IF NOT EXISTS sync_state (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS index_metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )
            self._migrate_document_paths(db)
            self._validate_embedding_identity(db)
            if self.vector_extension:
                self._create_vector_table(db)
            db.commit()

    @staticmethod
    def _migrate_document_paths(db: sqlite3.Connection) -> None:
        columns = {row["name"] for row in db.execute("PRAGMA table_info(documents)")}
        for name in (
            "relative_path",
            "parent_folder_id",
            "folder_ancestry",
        ):
            if name not in columns:
                default = "'[]'" if name == "folder_ancestry" else "''"
                db.execute(
                    f"ALTER TABLE documents ADD COLUMN {name} TEXT NOT NULL DEFAULT {default}"
                )
        db.execute("DROP INDEX IF EXISTS idx_documents_scope")

    def _create_vector_table(self, db: sqlite3.Connection) -> None:
        db.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS vec_chunks USING vec0("
            f"embedding float[{self.dimensions}] distance_metric=cosine)"
        )

    def _validate_embedding_identity(self, db: sqlite3.Connection) -> None:
        identity = self.embedding_identity
        if identity is None:
            return
        row = db.execute(
            "SELECT value FROM index_metadata WHERE key='embedding_identity'"
        ).fetchone()
        chunk_count = int(db.execute("SELECT COUNT(*) FROM chunks").fetchone()[0])
        if row is None:
            if chunk_count and self.enforce_identity:
                raise ReindexRequiredError(
                    "This legacy index contains vectors but no embedding identity, so their model "
                    "cannot be safely inferred. Run `google-drive-rag-mcp reindex --yes` to "
                    "rebuild it, "
                    "or set GOOGLE_DRIVE_RAG_DB_PATH/GOOGLE_DRIVE_RAG_INDEX_PROFILE to a new index."
                )
            if not chunk_count:
                if self.vector_extension:
                    db.execute("DROP TABLE IF EXISTS vec_chunks")
                self._write_embedding_identity(db, identity)
            return
        stored = json.loads(row["value"])
        expected = identity.as_dict()
        if stored != expected and self.enforce_identity:
            raise ReindexRequiredError(
                "Embedding configuration does not match this index. "
                f"Stored={stored}; configured={expected}. "
                "Run `google-drive-rag-mcp reindex --yes` or select a different database/profile."
            )

    @staticmethod
    def _write_embedding_identity(db: sqlite3.Connection, identity: EmbeddingIdentity) -> None:
        db.execute(
            "INSERT INTO index_metadata(key,value,updated_at) VALUES('embedding_identity',?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at",
            (json.dumps(identity.as_dict(), sort_keys=True), _now()),
        )

    def reset_index(self, identity: EmbeddingIdentity) -> None:
        """Delete generated index data and bind the empty index to a new embedding identity."""
        with self.connection() as db:
            db.execute("DELETE FROM chunks_fts")
            db.execute("DELETE FROM chunks")
            db.execute("DELETE FROM documents")
            db.execute("DELETE FROM sync_state")
            if self.vector_extension:
                db.execute("DROP TABLE IF EXISTS vec_chunks")
            self.dimensions = identity.dimensions
            self.embedding_identity = identity
            self._write_embedding_identity(db, identity)
            if self.vector_extension:
                self._create_vector_table(db)
            db.commit()

    def document_checksums(self) -> dict[str, str]:
        with self.connection() as db:
            return {
                row["id"]: row["checksum"]
                for row in db.execute("SELECT id, checksum FROM documents")
            }

    def document_fingerprints(self) -> dict[str, str]:
        with self.connection() as db:
            return {
                row["id"]: "\0".join(
                    (
                        row["checksum"],
                        row["relative_path"],
                        row["parent_folder_id"],
                        *json.loads(row["folder_ancestry"]),
                    )
                )
                for row in db.execute(
                    "SELECT id,checksum,relative_path,parent_folder_id,folder_ancestry "
                    "FROM documents"
                )
            }

    def replace_document(
        self, document: SourceDocument, chunks: Sequence[str], embeddings: Sequence[Sequence[float]]
    ) -> None:
        if len(chunks) != len(embeddings):
            raise ValueError("Each chunk must have an embedding")
        if any(len(embedding) != self.dimensions for embedding in embeddings):
            raise ValueError(f"Embedding dimension must be {self.dimensions}")
        with self.connection() as db:
            old_ids = [
                row["id"]
                for row in db.execute("SELECT id FROM chunks WHERE document_id = ?", (document.id,))
            ]
            if old_ids:
                placeholders = ",".join("?" for _ in old_ids)
                db.execute(f"DELETE FROM chunks_fts WHERE chunk_id IN ({placeholders})", old_ids)
                if self.vector_extension:
                    db.execute(f"DELETE FROM vec_chunks WHERE rowid IN ({placeholders})", old_ids)
            db.execute("DELETE FROM chunks WHERE document_id = ?", (document.id,))
            indexed_at = _now()
            db.execute(
                """INSERT INTO documents(
                       id,name,mime_type,modified_time,checksum,web_url,indexed_at,
                       relative_path,parent_folder_id,folder_ancestry)
                   VALUES(?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(id) DO UPDATE SET name=excluded.name, mime_type=excluded.mime_type,
                   modified_time=excluded.modified_time, checksum=excluded.checksum,
                   web_url=excluded.web_url, indexed_at=excluded.indexed_at,
                   relative_path=excluded.relative_path,
                   parent_folder_id=excluded.parent_folder_id,
                   folder_ancestry=excluded.folder_ancestry""",
                (
                    document.id,
                    document.name,
                    document.mime_type,
                    document.modified_time,
                    document.checksum,
                    document.web_url,
                    indexed_at,
                    document.relative_path,
                    document.parent_folder_id,
                    json.dumps(document.ancestor_folder_ids),
                ),
            )
            db.execute("DELETE FROM document_folder_ancestors WHERE document_id=?", (document.id,))
            db.executemany(
                "INSERT INTO document_folder_ancestors(document_id,folder_id,depth) VALUES(?,?,?)",
                (
                    (document.id, folder_id, depth)
                    for depth, folder_id in enumerate(document.ancestor_folder_ids)
                ),
            )
            for position, (text, embedding) in enumerate(zip(chunks, embeddings, strict=True)):
                cursor = db.execute(
                    "INSERT INTO chunks(document_id,position,text,embedding) VALUES(?,?,?,?)",
                    (document.id, position, text, _pack(embedding)),
                )
                chunk_id = int(cursor.lastrowid or 0)
                db.execute("INSERT INTO chunks_fts(chunk_id,text) VALUES(?,?)", (chunk_id, text))
                if self.vector_extension:
                    db.execute(
                        "INSERT INTO vec_chunks(rowid,embedding) VALUES(?,?)",
                        (chunk_id, _pack(embedding)),
                    )
            db.commit()

    def delete_documents_not_in(self, active_ids: set[str]) -> int:
        with self.connection() as db:
            stale_ids = [
                row["id"]
                for row in db.execute("SELECT id FROM documents")
                if row["id"] not in active_ids
            ]
            for document_id in stale_ids:
                chunk_ids = [
                    row["id"]
                    for row in db.execute(
                        "SELECT id FROM chunks WHERE document_id=?", (document_id,)
                    )
                ]
                if chunk_ids:
                    placeholders = ",".join("?" for _ in chunk_ids)
                    db.execute(
                        f"DELETE FROM chunks_fts WHERE chunk_id IN ({placeholders})", chunk_ids
                    )
                    if self.vector_extension:
                        db.execute(
                            f"DELETE FROM vec_chunks WHERE rowid IN ({placeholders})", chunk_ids
                        )
                db.execute("DELETE FROM documents WHERE id=?", (document_id,))
            db.commit()
            return len(stale_ids)

    def delete_document(self, document_id: str) -> bool:
        """Delete one document and its search rows, returning whether it existed."""
        with self.connection() as db:
            chunk_ids = [
                row["id"]
                for row in db.execute("SELECT id FROM chunks WHERE document_id=?", (document_id,))
            ]
            if chunk_ids:
                placeholders = ",".join("?" for _ in chunk_ids)
                db.execute(f"DELETE FROM chunks_fts WHERE chunk_id IN ({placeholders})", chunk_ids)
                if self.vector_extension:
                    db.execute(f"DELETE FROM vec_chunks WHERE rowid IN ({placeholders})", chunk_ids)
            cursor = db.execute("DELETE FROM documents WHERE id=?", (document_id,))
            db.commit()
            return cursor.rowcount > 0

    @staticmethod
    def _fts_query(query: str) -> str:
        tokens = [token.replace('"', "") for token in query.split() if token.strip('"')]
        return " OR ".join(f'"{token}"' for token in tokens)

    @staticmethod
    def _scope_predicate(scope_id: str, alias: str = "d") -> tuple[str, list[str]]:
        return (
            f"({alias}.id=? OR EXISTS ("
            "SELECT 1 FROM document_folder_ancestors requested_scope "
            f"WHERE requested_scope.document_id={alias}.id AND requested_scope.folder_id=?))",
            [scope_id.strip(), scope_id.strip()],
        )

    def keyword_scores(
        self,
        query: str,
        limit: int,
        scope_id: str,
    ) -> dict[int, float]:
        expression = self._fts_query(query)
        if not expression:
            return {}
        predicate, parameters = self._scope_predicate(scope_id)
        with self.connection() as db:
            rows = db.execute(
                "SELECT CAST(f.chunk_id AS INTEGER) AS id, bm25(chunks_fts) AS rank "
                "FROM chunks_fts f JOIN chunks c ON c.id=CAST(f.chunk_id AS INTEGER) "
                "JOIN documents d ON d.id=c.document_id "
                f"WHERE chunks_fts MATCH ? AND {predicate} ORDER BY rank LIMIT ?",
                [expression, *parameters, limit],
            )
            return {row["id"]: 1.0 / (1.0 + abs(float(row["rank"]))) for row in rows}

    def vector_scores(
        self,
        query_embedding: Sequence[float],
        limit: int,
        scope_id: str,
    ) -> dict[int, float]:
        if len(query_embedding) != self.dimensions:
            raise ValueError(f"Embedding dimension must be {self.dimensions}")
        with self.connection() as db:
            predicate, parameters = self._scope_predicate(scope_id)
            if self.vector_extension:
                rows = db.execute(
                    "SELECT c.id,vec_distance_cosine(c.embedding,?) AS distance "
                    "FROM chunks c JOIN documents d ON d.id=c.document_id "
                    f"WHERE {predicate} ORDER BY distance LIMIT ?",
                    [_pack(query_embedding), *parameters, limit],
                )
                return {row["id"]: max(0.0, 1.0 - float(row["distance"])) for row in rows}
            query_norm = math.sqrt(sum(value * value for value in query_embedding)) or 1.0
            scored: list[tuple[int, float]] = []
            for row in db.execute(
                "SELECT c.id,c.embedding FROM chunks c JOIN documents d ON d.id=c.document_id "
                f"WHERE {predicate}",
                parameters,
            ):
                candidate = _unpack(row["embedding"])
                norm = math.sqrt(sum(value * value for value in candidate)) or 1.0
                cosine = sum(a * b for a, b in zip(query_embedding, candidate, strict=True)) / (
                    query_norm * norm
                )
                scored.append((row["id"], max(0.0, cosine)))
            return dict(sorted(scored, key=lambda item: item[1], reverse=True)[:limit])

    def search_hits(
        self,
        scores: dict[int, float],
        limit: int,
        scope_id: str,
    ) -> list[SearchHit]:
        if not scores:
            return []
        ids = list(scores)
        placeholders = ",".join("?" for _ in ids)
        predicate, parameters = self._scope_predicate(scope_id)
        with self.connection() as db:
            rows = db.execute(
                f"""SELECT c.id,c.document_id,c.position,c.text,d.name,d.modified_time,
                           d.indexed_at,d.web_url,d.relative_path
                    FROM chunks c JOIN documents d ON d.id=c.document_id
                    WHERE c.id IN ({placeholders}) AND {predicate}""",
                [*ids, *parameters],
            )
            hits = [
                SearchHit(
                    chunk_id=row["id"],
                    document_id=row["document_id"],
                    document_name=row["name"],
                    text=row["text"],
                    score=scores[row["id"]],
                    modified_time=row["modified_time"],
                    indexed_at=row["indexed_at"],
                    web_url=row["web_url"],
                    position=row["position"],
                    relative_path=row["relative_path"],
                )
                for row in rows
            ]
        return sorted(hits, key=lambda hit: hit.score, reverse=True)[:limit]

    def get_document(self, document_id: str) -> dict[str, Any] | None:
        with self.connection() as db:
            document = db.execute(
                "SELECT d.* FROM documents d WHERE d.id=?",
                (document_id,),
            ).fetchone()
            if document is None:
                return None
            chunks = [
                row["text"]
                for row in db.execute(
                    "SELECT text FROM chunks WHERE document_id=? ORDER BY position", (document_id,)
                )
            ]
            return {"metadata": dict(document), "text": "\n\n".join(chunks)}

    def get_metadata(self, document_id: str) -> DocumentMetadata | None:
        with self.connection() as db:
            row = db.execute(
                """SELECT id,name,mime_type,modified_time,checksum,web_url,indexed_at,
                          relative_path,parent_folder_id,folder_ancestry
                   FROM documents WHERE id=?""",
                (document_id,),
            ).fetchone()
            return DocumentMetadata(**dict(row)) if row else None

    def set_state(self, key: str, value: Any) -> None:
        with self.connection() as db:
            db.execute(
                "INSERT INTO sync_state(key,value,updated_at) VALUES(?,?,?) "
                "ON CONFLICT(key) DO UPDATE SET "
                "value=excluded.value,updated_at=excluded.updated_at",
                (key, json.dumps(value), _now()),
            )
            db.commit()

    def get_state(self, key: str) -> Any | None:
        with self.connection() as db:
            row = db.execute("SELECT value FROM sync_state WHERE key=?", (key,)).fetchone()
        return json.loads(row["value"]) if row else None

    def status(self) -> dict[str, Any]:
        with self.connection() as db:
            documents = db.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
            chunks = db.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
            state_rows = db.execute("SELECT key,value,updated_at FROM sync_state").fetchall()
            identity_row = db.execute(
                "SELECT value FROM index_metadata WHERE key='embedding_identity'"
            ).fetchone()
        state = {
            row["key"]: {"value": json.loads(row["value"]), "updated_at": row["updated_at"]}
            for row in state_rows
        }
        public_identity = None
        if identity_row:
            identity = json.loads(identity_row["value"])
            public_identity = {
                key: identity[key] for key in ("provider", "model", "dimensions", "fingerprint")
            }
        return {
            "documents": documents,
            "chunks": chunks,
            "drive_root_folder_id": (
                state["drive_root_folder_id"]["value"] if "drive_root_folder_id" in state else None
            ),
            "last_sync": state.get("last_sync"),
            "vector_backend": "sqlite-vec" if self.vector_extension else "sqlite-python-fallback",
            "embedding_identity": public_identity,
        }
