import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from tgram.adapters.db import get_connection
from tgram.domain.channel import Channel


class ChannelRepo:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)

    @contextmanager
    def _conn(self):
        conn = get_connection(self.db_path)
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def upsert(self, ch: Channel) -> None:
        """Insert or update title/type/is_forum. Never overwrites enabled or last_fetched_id."""
        with self._conn() as c:
            c.execute(
                """INSERT INTO channels (chat_id, title, type, is_forum, enabled)
                   VALUES (?, ?, ?, ?, 0)
                   ON CONFLICT(chat_id) DO UPDATE SET
                       title    = excluded.title,
                       type     = excluded.type,
                       is_forum = excluded.is_forum""",
                (ch.chat_id, ch.title, ch.type, int(ch.is_forum)),
            )

    def update_last_fetched(self, chat_id: int, last_id: int) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._conn() as c:
            c.execute(
                """UPDATE channels
                   SET last_fetched_id = MAX(COALESCE(last_fetched_id, 0), ?),
                       last_fetch_at   = ?
                   WHERE chat_id = ?""",
                (last_id, now, chat_id),
            )

    def set_enabled(self, chat_id: int, enabled: bool) -> None:
        with self._conn() as c:
            c.execute(
                "UPDATE channels SET enabled = ? WHERE chat_id = ?",
                (int(enabled), chat_id),
            )

    def get(self, chat_id: int) -> Channel | None:
        with self._conn() as c:
            row = c.execute(
                "SELECT * FROM channels WHERE chat_id = ?", (chat_id,)
            ).fetchone()
        return self._to_channel(row) if row else None

    def list_all(self) -> list[Channel]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT * FROM channels ORDER BY title"
            ).fetchall()
        return [self._to_channel(r) for r in rows]

    def list_enabled(self) -> list[Channel]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT * FROM channels WHERE enabled = 1 ORDER BY title"
            ).fetchall()
        return [self._to_channel(r) for r in rows]

    @staticmethod
    def _to_channel(row) -> Channel:
        return Channel(
            chat_id=row["chat_id"],
            title=row["title"],
            type=row["type"],
            is_forum=bool(row["is_forum"]),
            last_fetched_id=row["last_fetched_id"],
            oldest_fetched_id=row["oldest_fetched_id"],
            last_fetch_at=datetime.fromisoformat(row["last_fetch_at"])
                if row["last_fetch_at"] else None,
            enabled=bool(row["enabled"]),
        )
