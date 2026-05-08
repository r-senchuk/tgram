import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from tgram.domain.message import Message

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

    def reply_root(self, chat_id: int, message_id: int) -> int:
        """Walk the reply chain upward and return the root message ID.
        Returns message_id itself if no chain exists or parent not stored yet."""
        current = message_id
        seen: set[int] = set()
        with self._conn() as c:
            while current not in seen:
                seen.add(current)
                row = c.execute(
                    "SELECT reply_to_message_id FROM messages WHERE chat_id=? AND id=?",
                    (chat_id, current),
                ).fetchone()
                if not row or row[0] is None:
                    return current
                current = row[0]
        return current  # cycle guard
