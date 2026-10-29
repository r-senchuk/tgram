import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from tgram.domain.message import Message
from tgram.domain.threading import resolve_root

MIGRATIONS_DIR = Path(__file__).parent.parent / "migrations"


class MessageRepo:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._apply_schema()

    def _apply_schema(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            for sql_file in sorted(MIGRATIONS_DIR.glob("*.sql")):
                conn.executescript(sql_file.read_text())

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    # ── writes ────────────────────────────────────────────────────────────────

    @staticmethod
    def _row(msg: Message) -> tuple:
        return (
            msg.chat_id, msg.id,
            msg.date.isoformat(),
            msg.text,
            msg.from_user_id, msg.username,
            msg.reply_to_message_id,
            msg.reply_to_top_message_id,
            msg.virtual_topic_id,
            msg.media_type,
            msg.raw_json,
        )

    def save(self, msg: Message) -> None:
        with self._conn() as c:
            c.execute(
                """INSERT OR REPLACE INTO messages
                   (chat_id, id, date, text, from_user_id, username,
                    reply_to_message_id, reply_to_top_message_id,
                    virtual_topic_id, media_type, raw_json)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                self._row(msg),
            )

    def save_many(self, msgs: list[Message]) -> None:
        """Insert a batch of messages in a single transaction."""
        with self._conn() as c:
            c.executemany(
                """INSERT OR REPLACE INTO messages
                   (chat_id, id, date, text, from_user_id, username,
                    reply_to_message_id, reply_to_top_message_id,
                    virtual_topic_id, media_type, raw_json)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                [self._row(m) for m in msgs],
            )

    # ── existence / bounds ────────────────────────────────────────────────────

    def exists(self, chat_id: int, message_id: int) -> bool:
        with self._conn() as c:
            row = c.execute(
                "SELECT 1 FROM messages WHERE chat_id=? AND id=?",
                (chat_id, message_id),
            ).fetchone()
            return row is not None

    def existing_ids(self, chat_id: int, ids: list[int]) -> set[int]:
        """Return the subset of message IDs that already exist in the database for chat_id."""
        if not ids:
            return set()
        result: set[int] = set()
        CHUNK = 500
        with self._conn() as c:
            for i in range(0, len(ids), CHUNK):
                chunk = ids[i : i + CHUNK]
                placeholders = ",".join("?" for _ in chunk)
                rows = c.execute(
                    f"SELECT id FROM messages WHERE chat_id = ? AND id IN ({placeholders})",
                    [chat_id, *chunk],
                ).fetchall()
                result.update(r[0] for r in rows)
        return result

    def max_id(self, chat_id: int) -> int | None:
        with self._conn() as c:
            row = c.execute(
                "SELECT MAX(id) FROM messages WHERE chat_id=?", (chat_id,)
            ).fetchone()
            return row[0] if row and row[0] is not None else None

    def min_id(self, chat_id: int) -> int | None:
        with self._conn() as c:
            row = c.execute(
                "SELECT MIN(id) FROM messages WHERE chat_id=?", (chat_id,)
            ).fetchone()
            return row[0] if row and row[0] is not None else None

    def count(self, chat_id: int) -> int:
        with self._conn() as c:
            return c.execute(
                "SELECT COUNT(*) FROM messages WHERE chat_id=?", (chat_id,)
            ).fetchone()[0]

    def get_by_id(self, message_id: int, chat_id: int | None = None) -> dict | None:
        """Return the first message row matching message_id, optionally scoped to chat_id."""
        sql = """SELECT id, chat_id, date, text, username, from_user_id,
                        reply_to_message_id, reply_to_top_message_id, virtual_topic_id
                 FROM messages WHERE id = ?"""
        params: list = [message_id]
        if chat_id is not None:
            sql += " AND chat_id = ?"
            params.append(chat_id)
        sql += " LIMIT 1"
        with self._conn() as c:
            row = c.execute(sql, params).fetchone()
        return dict(row) if row else None

    # ── gap detection ─────────────────────────────────────────────────────────

    def find_gaps(self, chat_id: int) -> list[tuple[int, int]]:
        """Detect gaps using a SQL window function — no Python-side ID list."""
        with self._conn() as c:
            rows = c.execute(
                """SELECT id + 1 AS gap_start,
                          next_id - 1 AS gap_end
                   FROM (
                       SELECT id,
                              LEAD(id) OVER (ORDER BY id) AS next_id
                       FROM messages
                       WHERE chat_id = ?
                   )
                   WHERE next_id > id + 1""",
                (chat_id,),
            ).fetchall()
        return [(r[0], r[1]) for r in rows]

    # ── topic helpers ─────────────────────────────────────────────────────────

    def thread_root_of(self, chat_id: int, message_id: int) -> int:
        """Return the stored virtual_topic_id of message_id, or message_id if not stored."""
        with self._conn() as c:
            row = c.execute(
                "SELECT virtual_topic_id FROM messages WHERE chat_id=? AND id=?",
                (chat_id, message_id),
            ).fetchone()
            if row and row[0] is not None:
                return row[0]
            return message_id

    # Alias for backward compatibility
    reply_root = thread_root_of

    def repair_virtual_topics(self, chat_id: int | None = None, dry_run: bool = False) -> int:
        """Recompute virtual_topic_id for all messages (or scoped to chat_id).

        Returns the number of rows updated (or that would be updated if dry_run=True).
        """
        with self._conn() as c:
            if not dry_run:
                cleanup_sql = """
                    UPDATE messages
                    SET reply_to_message_id = NULL
                    WHERE reply_to_message_id IS NOT NULL
                      AND json_valid(raw_json)
                      AND json_extract(raw_json, '$.reply_to.reply_to_peer_id') IS NOT NULL
                """
                if chat_id is not None:
                    cleanup_sql += " AND chat_id = ?"
                    c.execute(cleanup_sql, (chat_id,))
                else:
                    c.execute(cleanup_sql)

            select_sql = """
                SELECT chat_id, id,
                       CASE WHEN json_valid(raw_json) AND json_extract(raw_json, '$.reply_to.reply_to_peer_id') IS NOT NULL
                            THEN NULL
                            ELSE reply_to_message_id
                       END AS reply_to_message_id,
                       reply_to_top_message_id,
                       virtual_topic_id
                FROM messages
            """
            params: tuple = ()
            if chat_id is not None:
                select_sql += " WHERE chat_id = ?"
                params = (chat_id,)
            select_sql += " ORDER BY chat_id, id"

            rows = c.execute(select_sql, params).fetchall()

            roots: dict[int, int] = {}
            current_chat_id: int | None = None
            updates: list[tuple[int, int, int]] = []

            for row in rows:
                cid = row[0]
                mid = row[1]
                rep = row[2]
                top = row[3]
                old_vtid = row[4]

                if cid != current_chat_id:
                    roots = {}
                    current_chat_id = cid

                new_vtid = resolve_root(mid, rep, top, roots)
                roots[mid] = new_vtid
                if new_vtid != old_vtid:
                    updates.append((new_vtid, cid, mid))

            if not dry_run and updates:
                c.executemany(
                    "UPDATE messages SET virtual_topic_id = ? WHERE chat_id = ? AND id = ?",
                    updates,
                )

            return len(updates)
