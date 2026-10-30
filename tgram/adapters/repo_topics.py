import sqlite3
from contextlib import contextmanager
from pathlib import Path

from tgram.adapters.db import get_connection
from tgram.domain.topic import Topic


class TopicRepo:
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

    def save(self, topic: Topic) -> None:
        with self._conn() as c:
            c.execute(
                "INSERT OR REPLACE INTO topics (chat_id, topic_id, title) VALUES (?,?,?)",
                (topic.chat_id, topic.topic_id, topic.title),
            )

    def get(self, chat_id: int, topic_id: int) -> Topic | None:
        with self._conn() as c:
            row = c.execute(
                "SELECT chat_id, topic_id, title FROM topics WHERE chat_id=? AND topic_id=?",
                (chat_id, topic_id),
            ).fetchone()
            return Topic(**dict(row)) if row else None

    def list_for_chat(self, chat_id: int) -> list[Topic]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT chat_id, topic_id, title FROM topics WHERE chat_id=? ORDER BY topic_id",
                (chat_id,),
            ).fetchall()
            return [Topic(**dict(r)) for r in rows]

    def unknown_topic_ids(self, chat_id: int) -> list[int]:
        """Return topic IDs seen in messages but not yet named in the topics table."""
        with self._conn() as c:
            rows = c.execute(
                """SELECT DISTINCT reply_to_top_message_id
                   FROM messages
                   WHERE chat_id = ? AND reply_to_top_message_id IS NOT NULL
                     AND reply_to_top_message_id NOT IN (
                         SELECT topic_id FROM topics WHERE chat_id = ?
                     )
                   ORDER BY reply_to_top_message_id""",
                (chat_id, chat_id),
            ).fetchall()
            return [r[0] for r in rows]

    def stats_for_chat(self, chat_id: int | None) -> list[dict]:
        """Return topics with message count and last activity, sorted by msg_count desc.

        If chat_id is None, returns topics across all chats (with chat_id included).
        """
        with self._conn() as c:
            if chat_id is not None:
                rows = c.execute(
                    """SELECT t.chat_id, t.topic_id, t.title,
                              COUNT(m.id) as msg_count,
                              MAX(m.date) as last_active
                       FROM topics t
                       LEFT JOIN messages m
                         ON m.chat_id = t.chat_id AND m.reply_to_top_message_id = t.topic_id
                       WHERE t.chat_id = ?
                       GROUP BY t.chat_id, t.topic_id
                       ORDER BY msg_count DESC""",
                    (chat_id,),
                ).fetchall()
            else:
                rows = c.execute(
                    """SELECT t.chat_id, t.topic_id, t.title,
                              COUNT(m.id) as msg_count,
                              MAX(m.date) as last_active
                       FROM topics t
                       LEFT JOIN messages m
                         ON m.chat_id = t.chat_id AND m.reply_to_top_message_id = t.topic_id
                       GROUP BY t.chat_id, t.topic_id
                       ORDER BY msg_count DESC""",
                ).fetchall()
            return [dict(r) for r in rows]
