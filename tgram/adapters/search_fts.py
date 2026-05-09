from __future__ import annotations

import re
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tgram.adapters.repo_embeddings import EmbeddingRepo


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


def _clean_fts_query(query: str, match_any: bool = False) -> str:
    """Sanitize a user query for FTS5 MATCH.

    match_any=False (default, for `search` command):
        Terms are implicitly ANDed — all must match. Preserves "phrase" and term*.
    match_any=True (for `ask` command):
        Extracts content words (≥4 chars) and ORs them — any match retrieves
        the message. Better for natural language questions where no single
        message contains every word.
    """
    # Remove chars FTS5 treats as syntax errors (keep " and * for intentional operators)
    cleaned = re.sub(r"[?!.,;:@#%&=~`|\\/<>{}[\]_']", " ", query)
    terms = cleaned.split()
    if not terms:
        return '""'
    if match_any:
        content = [t for t in terms if len(t) >= 4]
        if content:
            return " OR ".join(content)
        return " OR ".join(terms)
    return " ".join(terms)


def _rrf_merge(
    fts_hits: list[SearchHit],
    vec_hits: list[tuple[int, int, float]],
    k: int = 60,
    limit: int = 20,
) -> list[tuple[int, int]]:
    """Reciprocal Rank Fusion of FTS and vector result lists."""
    scores: dict[tuple[int, int], float] = {}
    for rank, hit in enumerate(fts_hits):
        key = (hit.chat_id, hit.message_id)
        scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank + 1)
    for rank, (chat_id, msg_id, _dist) in enumerate(vec_hits):
        key = (chat_id, msg_id)
        scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank + 1)
    return sorted(scores, key=lambda k: scores[k], reverse=True)[:limit]


class FTSSearch:
    def __init__(self, db_path: Path, embedding_repo: EmbeddingRepo | None = None):
        self.db_path = Path(db_path)
        self.embedding_repo = embedding_repo

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
        match_any: bool = False,
        query_vector: list[float] | None = None,
    ) -> list[SearchHit]:
        # Fetch more candidates when doing RRF so both lists are deep enough
        fetch_limit = limit * 3 if (query_vector and self.embedding_repo) else limit

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
        params: list = [_clean_fts_query(query, match_any=match_any)]

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
        params.append(fetch_limit)

        with self._conn() as c:
            rows = c.execute(sql, params).fetchall()

        hit_map: dict[tuple[int, int], SearchHit] = {}
        fts_hits: list[SearchHit] = []
        for r in rows:
            h = SearchHit(
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
            fts_hits.append(h)
            hit_map[(h.chat_id, h.message_id)] = h

        if not (query_vector and self.embedding_repo):
            return fts_hits[:limit]

        # Hybrid: merge FTS + vector results via RRF
        vec_hits = self.embedding_repo.search_similar(
            query_vector, chat_id=chat_id, limit=fetch_limit
        )

        # Fetch SearchHit objects for vector-only results (not in FTS list)
        vec_only_keys = [
            (cid, mid) for cid, mid, _ in vec_hits
            if (cid, mid) not in hit_map
        ]
        if vec_only_keys:
            self._fetch_hits_by_ids(vec_only_keys, hit_map)

        merged_keys = _rrf_merge(fts_hits, vec_hits, limit=limit)
        return [hit_map[k] for k in merged_keys if k in hit_map]

    def _fetch_hits_by_ids(
        self,
        keys: list[tuple[int, int]],
        hit_map: dict[tuple[int, int], SearchHit],
    ) -> None:
        """Load SearchHit rows for (chat_id, message_id) pairs not yet in hit_map."""
        if not keys:
            return
        placeholders = ",".join("(?,?)" for _ in keys)
        flat = [v for pair in keys for v in pair]
        sql = f"""
            SELECT m.chat_id, m.id, m.date, m.text, m.username, m.from_user_id,
                   m.reply_to_top_message_id AS topic_id,
                   t.title AS topic_title,
                   '' AS snippet
            FROM messages m
            LEFT JOIN topics t
                ON t.chat_id = m.chat_id
               AND t.topic_id = m.reply_to_top_message_id
            WHERE (m.chat_id, m.id) IN ({placeholders})
        """
        with self._conn() as c:
            rows = c.execute(sql, flat).fetchall()
        for r in rows:
            h = SearchHit(
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
            hit_map[(h.chat_id, h.message_id)] = h

    def get_context(
        self, hit: SearchHit, before: int = 3, after: int = 3,
        use_virtual_topic: bool = False,
    ) -> list[ContextMessage]:
        """Return messages surrounding a hit within the same topic thread.

        use_virtual_topic — when True, filter by virtual_topic_id instead of
        reply_to_top_message_id (for non-forum channels with virtual topics).
        """
        with self._conn() as c:
            if hit.topic_id is not None:
                col = "virtual_topic_id" if use_virtual_topic else "reply_to_top_message_id"
                topic_filter = f"AND {col} = :topic_id"
            else:
                topic_filter = "AND reply_to_top_message_id IS NULL AND virtual_topic_id IS NULL"

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
