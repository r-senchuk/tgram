import sqlite3
import struct
from contextlib import contextmanager
from pathlib import Path

import sqlite_vec

MIGRATIONS_DIR = Path(__file__).parent.parent / "migrations"


def _pack(vector: list[float]) -> bytes:
    return struct.pack(f"{len(vector)}f", *vector)


class EmbeddingRepo:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self._apply_schema()

    def _apply_schema(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            for sql_file in sorted(MIGRATIONS_DIR.glob("*.sql")):
                if sql_file.name == "005_embeddings_chunked.sql":
                    # This migration does DROP+RENAME — skip if already applied.
                    cols = {r[1] for r in conn.execute("PRAGMA table_info(embeddings)").fetchall()}
                    if "chunk_idx" in cols:
                        continue
                conn.executescript(sql_file.read_text())

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def save_many(self, rows: list[tuple[int, int, int, list[float], str]]) -> None:
        """Store embeddings. rows = [(chat_id, message_id, chunk_idx, vector, model), ...]"""
        with self._conn() as c:
            c.executemany(
                "INSERT OR REPLACE INTO embeddings"
                " (chat_id, message_id, chunk_idx, vector, model)"
                " VALUES (?, ?, ?, ?, ?)",
                [(chat_id, msg_id, chunk_idx, _pack(vec), model)
                 for chat_id, msg_id, chunk_idx, vec, model in rows],
            )

    def ids_without_embeddings(
        self,
        chat_id: int | None,
        model: str,
        limit: int = 500,
    ) -> list[tuple[int, int, str]]:
        """Return (chat_id, message_id, text) for messages not yet embedded."""
        sql = """
            SELECT m.chat_id, m.id, COALESCE(m.text, '') AS text
            FROM messages m
            LEFT JOIN embeddings e
                ON e.chat_id = m.chat_id AND e.message_id = m.id AND e.model = ?
            WHERE e.message_id IS NULL
              AND COALESCE(m.text, '') != ''
        """
        params: list = [model]
        if chat_id is not None:
            sql += " AND m.chat_id = ?"
            params.append(chat_id)
        sql += " LIMIT ?"
        params.append(limit)

        with self._conn() as c:
            rows = c.execute(sql, params).fetchall()
        return [(r["chat_id"], r["id"], r["text"]) for r in rows]

    def count_missing(self, chat_id: int | None, model: str) -> int:
        """Count messages that still need embeddings."""
        sql = """
            SELECT COUNT(*) FROM messages m
            LEFT JOIN embeddings e
                ON e.chat_id = m.chat_id AND e.message_id = m.id AND e.model = ?
            WHERE e.message_id IS NULL
              AND COALESCE(m.text, '') != ''
        """
        params: list = [model]
        if chat_id is not None:
            sql += " AND m.chat_id = ?"
            params.append(chat_id)
        with self._conn() as c:
            return c.execute(sql, params).fetchone()[0]

    def search_similar(
        self,
        query_vector: list[float],
        *,
        chat_id: int | None = None,
        topic_id: int | None = None,
        since: str | None = None,
        until: str | None = None,
        limit: int = 50,
    ) -> list[tuple[int, int, float]]:
        """Return (chat_id, message_id, distance) ordered by cosine distance ASC.

        Groups by message so each message appears once at its best-matching chunk distance.
        """
        packed = _pack(query_vector)
        if topic_id is None and since is None and until is None:
            sql = """
                SELECT chat_id, message_id,
                       MIN(vec_distance_cosine(vector, ?)) AS dist
                FROM embeddings
                WHERE (? IS NULL OR chat_id = ?)
                GROUP BY chat_id, message_id
                ORDER BY dist ASC
                LIMIT ?
            """
            params: list = [packed, chat_id, chat_id, limit]
        else:
            sql = """
                SELECT e.chat_id, e.message_id,
                       MIN(vec_distance_cosine(e.vector, ?)) AS dist
                FROM embeddings e
                JOIN messages m ON m.chat_id = e.chat_id AND m.id = e.message_id
                WHERE 1=1
            """
            params = [packed]
            if chat_id is not None:
                sql += " AND e.chat_id = ?"
                params.append(chat_id)
            if topic_id is not None:
                sql += " AND m.reply_to_top_message_id = ?"
                params.append(topic_id)
            if since is not None:
                sql += " AND m.date >= ?"
                params.append(since)
            if until is not None:
                sql += " AND m.date <= ?"
                params.append(until)
            sql += """
                GROUP BY e.chat_id, e.message_id
                ORDER BY dist ASC
                LIMIT ?
            """
            params.append(limit)

        with self._conn() as c:
            rows = c.execute(sql, params).fetchall()
        return [(r["chat_id"], r["message_id"], r["dist"]) for r in rows]
