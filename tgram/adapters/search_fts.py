import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SearchHit:
    chat_id: int
    message_id: int
    date: str
    text: str
    username: str | None
    from_user_id: int | None
    topic_id: int | None
    topic_title: str | None
    snippet: str


@dataclass(frozen=True)
class ContextMessage:
    message_id: int
    date: str
    text: str | None
    username: str | None
    from_user_id: int | None
    is_hit: bool  # True = the search hit itself


class FTSSearch:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def search(
        self,
        query: str,
        *,
        chat_id: int | None = None,
        topic_id: int | None = None,
        since: str | None = None,
        until: str | None = None,
        limit: int = 20,
    ) -> list[SearchHit]:
        sql = """
            SELECT m.chat_id, m.id, m.date, m.text, m.username, m.from_user_id,
                   m.reply_to_top_message_id AS topic_id,
                   t.title AS topic_title,
                   snippet(messages_fts, 0, '>', '<', '…', 16) AS snippet,
                   bm25(messages_fts) AS score
            FROM messages_fts
            JOIN messages m ON m.rowid = messages_fts.rowid
            LEFT JOIN topics t
                ON t.chat_id = m.chat_id
               AND t.topic_id = m.reply_to_top_message_id
            WHERE messages_fts MATCH ?
        """
        params: list = [query]

        if chat_id is not None:
            sql += " AND m.chat_id = ?"
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

        sql += " ORDER BY score LIMIT ?"
        params.append(limit)

        with self._conn() as c:
            rows = c.execute(sql, params).fetchall()

        return [
            SearchHit(
                chat_id=r["chat_id"],
                message_id=r["id"],
                date=r["date"],
                text=r["text"] or "",
                username=r["username"],
                from_user_id=r["from_user_id"],
                topic_id=r["topic_id"],
                topic_title=r["topic_title"],
                snippet=r["snippet"],
            )
            for r in rows
        ]

    def get_context(
        self, hit: SearchHit, before: int = 3, after: int = 3
    ) -> list[ContextMessage]:
        """Return messages surrounding a hit within the same topic thread."""
        with self._conn() as c:
            # Messages in the same topic (or same chat if no topic), around the hit ID
            if hit.topic_id is not None:
                topic_filter = "AND reply_to_top_message_id = :topic_id"
            else:
                topic_filter = "AND reply_to_top_message_id IS NULL"

            before_rows = c.execute(
                f"""SELECT id, date, text, username, from_user_id FROM messages
                    WHERE chat_id = :chat_id {topic_filter} AND id < :mid
                    ORDER BY id DESC LIMIT :n""",
                {"chat_id": hit.chat_id, "topic_id": hit.topic_id,
                 "mid": hit.message_id, "n": before},
            ).fetchall()

            after_rows = c.execute(
                f"""SELECT id, date, text, username, from_user_id FROM messages
                    WHERE chat_id = :chat_id {topic_filter} AND id > :mid
                    ORDER BY id ASC LIMIT :n""",
                {"chat_id": hit.chat_id, "topic_id": hit.topic_id,
                 "mid": hit.message_id, "n": after},
            ).fetchall()

        def to_ctx(row, is_hit=False) -> ContextMessage:
            return ContextMessage(
                message_id=row["id"],
                date=row["date"],
                text=row["text"],
                username=row["username"],
                from_user_id=row["from_user_id"],
                is_hit=is_hit,
            )

        hit_row = ContextMessage(
            message_id=hit.message_id, date=hit.date, text=hit.text,
            username=hit.username, from_user_id=hit.from_user_id, is_hit=True,
        )
        return (
            [to_ctx(r) for r in reversed(before_rows)]
            + [hit_row]
            + [to_ctx(r) for r in after_rows]
        )

    def rebuild(self) -> int:
        """Rebuild FTS index from scratch. Returns count of indexed rows."""
        with self._conn() as c:
            c.execute("INSERT INTO messages_fts(messages_fts) VALUES ('rebuild')")
            c.commit()
            count = c.execute("SELECT COUNT(*) FROM messages_fts").fetchone()[0]
        return count
