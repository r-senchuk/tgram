from __future__ import annotations

import re
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
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
    virtual_topic_id: int | None = None
    reply_to_message_id: int | None = None


@dataclass(frozen=True)
class ContextMessage:
    message_id: int
    date: str
    text: str | None
    username: str | None
    from_user_id: int | None
    is_hit: bool  # True = the search hit itself
    chat_id: int = 0
    reply_to_message_id: int | None = None
    skipped_before: int = 0


def _parse_iso(s: str) -> datetime:
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


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
    cleaned = re.sub(r"[?!.,;:@#%&=~`|\\/<>{}[\]_'()+\-^]", " ", query)
    if cleaned.count('"') % 2 == 1:
        cleaned = cleaned.replace('"', " ")

    raw_tokens = cleaned.split()
    tokens: list[str] = []
    for t in raw_tokens:
        t = t.lstrip("*")
        if not t:
            continue
        tokens.append(t)

    if not tokens:
        return '""'

    if len(tokens) == 1 and tokens[0].upper() in {"AND", "OR", "NOT", "NEAR"}:
        return '""'

    processed: list[str] = []
    for t in tokens:
        if t.upper() in {"AND", "OR", "NOT", "NEAR"}:
            processed.append(t.lower())
        else:
            processed.append(t)

    if match_any:
        clean_tokens = [t.replace('"', "").replace("*", "") for t in processed]
        clean_tokens = [t for t in clean_tokens if t]
        if not clean_tokens:
            return '""'
        content = [t for t in clean_tokens if len(t) >= 4]
        if content:
            return " OR ".join(content)
        return " OR ".join(clean_tokens)

    return " ".join(processed)


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

        fts_query = _clean_fts_query(query, match_any=match_any)
        rows = []
        if fts_query != '""':
            sql = """
                SELECT m.chat_id, m.id, m.date, m.text, m.username, m.from_user_id,
                       m.reply_to_top_message_id AS topic_id,
                       t.title AS topic_title,
                       snippet(messages_fts, 0, '>', '<', '…', 16) AS snippet,
                       bm25(messages_fts) AS score,
                       m.virtual_topic_id,
                       m.reply_to_message_id
                FROM messages_fts
                JOIN messages m ON m.rowid = messages_fts.rowid
                LEFT JOIN topics t
                    ON t.chat_id = m.chat_id
                   AND t.topic_id = m.reply_to_top_message_id
                WHERE messages_fts MATCH ?
            """
            params: list = [fts_query]

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

            try:
                with self._conn() as c:
                    rows = c.execute(sql, params).fetchall()
            except sqlite3.OperationalError:
                rows = []

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
                virtual_topic_id=r["virtual_topic_id"],
                reply_to_message_id=r["reply_to_message_id"],
            )
            fts_hits.append(h)
            hit_map[(h.chat_id, h.message_id)] = h

        if not (query_vector and self.embedding_repo):
            return fts_hits[:limit]

        # Hybrid: merge FTS + vector results via RRF
        vec_hits = self.embedding_repo.search_similar(
            query_vector,
            chat_id=chat_id,
            topic_id=topic_id,
            since=since,
            until=until,
            limit=fetch_limit,
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
                   m.virtual_topic_id,
                   m.reply_to_message_id
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
                snippet=(r["text"] or "")[:160],
                virtual_topic_id=r["virtual_topic_id"],
                reply_to_message_id=r["reply_to_message_id"],
            )
            hit_map[(h.chat_id, h.message_id)] = h

    def get_context(
        self,
        hit: SearchHit,
        before: int = 3,
        after: int = 3,
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
                topic_filter = "AND reply_to_top_message_id IS NULL"

            before_rows = c.execute(
                f"""SELECT id, date, text, username, from_user_id, reply_to_message_id FROM messages
                    WHERE chat_id = :chat_id {topic_filter} AND id < :mid
                    ORDER BY id DESC LIMIT :n""",
                {"chat_id": hit.chat_id, "topic_id": hit.topic_id,
                 "mid": hit.message_id, "n": before},
            ).fetchall()

            after_rows = c.execute(
                f"""SELECT id, date, text, username, from_user_id, reply_to_message_id FROM messages
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
                chat_id=hit.chat_id,
                reply_to_message_id=row["reply_to_message_id"],
                skipped_before=0,
            )

        hit_row = ContextMessage(
            message_id=hit.message_id,
            date=hit.date,
            text=hit.text,
            username=hit.username,
            from_user_id=hit.from_user_id,
            is_hit=True,
            chat_id=hit.chat_id,
            reply_to_message_id=hit.reply_to_message_id,
            skipped_before=0,
        )
        return (
            [to_ctx(r) for r in reversed(before_rows)]
            + [hit_row]
            + [to_ctx(r) for r in after_rows]
        )

    def get_conversation(
        self,
        hit: SearchHit,
        *,
        max_thread_msgs: int = 12,
        window: int = 2,
        window_max_gap_min: int = 30,
    ) -> list[ContextMessage]:
        """Reconstruct a readable conversation around a hit.

        Combines:
        1. Thread selection: root + hit's ancestor chain + hit + direct replies + nearest thread msgs (up to max_thread_msgs).
        2. Temporal window: up to ±window messages in the same topic within window_max_gap_min minutes of hit.
        Returns deduplicated, chronologically sorted ContextMessages with skipped_before indicators.
        """
        if max_thread_msgs <= 0:
            max_thread_msgs = 12

        # 1. Resolve hit's metadata if missing
        vtid = hit.virtual_topic_id
        reply_to_msg_id = hit.reply_to_message_id
        topic_id = hit.topic_id

        if vtid is None:
            with self._conn() as c:
                row = c.execute(
                    "SELECT virtual_topic_id, reply_to_message_id, reply_to_top_message_id FROM messages WHERE chat_id = ? AND id = ?",
                    (hit.chat_id, hit.message_id),
                ).fetchone()
                if row:
                    vtid = row["virtual_topic_id"]
                    reply_to_msg_id = row["reply_to_message_id"]
                    topic_id = row["reply_to_top_message_id"]

        if vtid is None:
            vtid = hit.message_id

        # 2. Thread selection
        with self._conn() as c:
            raw_thread = c.execute(
                """
                SELECT id, date, text, username, from_user_id, reply_to_message_id
                FROM messages
                WHERE chat_id = ? AND virtual_topic_id = ?
                ORDER BY id ASC
                """,
                (hit.chat_id, vtid),
            ).fetchall()

        thread_rows = [dict(r) for r in raw_thread]
        by_id = {r["id"]: r for r in thread_rows}

        if hit.message_id not in by_id:
            hit_dict = {
                "id": hit.message_id,
                "date": hit.date,
                "text": hit.text,
                "username": hit.username,
                "from_user_id": hit.from_user_id,
                "reply_to_message_id": reply_to_msg_id,
            }
            by_id[hit.message_id] = hit_dict
            thread_rows.append(hit_dict)
            thread_rows.sort(key=lambda r: r["id"])

        if len(thread_rows) <= max_thread_msgs:
            selected_thread_ids = {r["id"] for r in thread_rows}
        else:
            # Priority 1: root
            root_id = thread_rows[0]["id"]
            if vtid in by_id:
                root_id = vtid
            selected_order: list[int] = [root_id]

            # Priority 3: hit itself (ensuring root and hit are always present)
            if hit.message_id not in selected_order:
                selected_order.append(hit.message_id)

            # Priority 2: ancestor path of hit (closest to hit first)
            ancestors: list[int] = []
            visited = {hit.message_id}
            curr = by_id[hit.message_id].get("reply_to_message_id")
            while curr is not None and curr in by_id and curr not in visited:
                visited.add(curr)
                ancestors.append(curr)
                curr = by_id[curr].get("reply_to_message_id")

            for aid in ancestors:
                if len(selected_order) >= max_thread_msgs:
                    break
                if aid not in selected_order:
                    selected_order.append(aid)

            # Priority 4: direct replies to hit
            direct_replies = [
                r["id"] for r in thread_rows
                if r.get("reply_to_message_id") == hit.message_id
            ]
            for rid in direct_replies:
                if len(selected_order) >= max_thread_msgs:
                    break
                if rid not in selected_order:
                    selected_order.append(rid)

            # Priority 5: remaining thread members nearest to hit.message_id
            remaining = sorted(
                [r["id"] for r in thread_rows if r["id"] not in selected_order],
                key=lambda x: abs(x - hit.message_id),
            )
            for rid in remaining:
                if len(selected_order) >= max_thread_msgs:
                    break
                selected_order.append(rid)

            selected_thread_ids = set(selected_order[:max_thread_msgs])

        # 3. Temporal Window
        valid_window_rows: list[dict] = []
        if window > 0:
            if topic_id is not None:
                topic_filter = "AND reply_to_top_message_id = :topic_id"
            else:
                topic_filter = "AND reply_to_top_message_id IS NULL"

            with self._conn() as c:
                before_w = c.execute(
                    f"""
                    SELECT id, date, text, username, from_user_id, reply_to_message_id
                    FROM messages
                    WHERE chat_id = :chat_id {topic_filter} AND id < :mid
                    ORDER BY id DESC LIMIT :w
                    """,
                    {"chat_id": hit.chat_id, "topic_id": topic_id, "mid": hit.message_id, "w": window},
                ).fetchall()

                after_w = c.execute(
                    f"""
                    SELECT id, date, text, username, from_user_id, reply_to_message_id
                    FROM messages
                    WHERE chat_id = :chat_id {topic_filter} AND id > :mid
                    ORDER BY id ASC LIMIT :w
                    """,
                    {"chat_id": hit.chat_id, "topic_id": topic_id, "mid": hit.message_id, "w": window},
                ).fetchall()

            try:
                hit_dt = _parse_iso(hit.date)
            except (ValueError, TypeError):
                hit_dt = None

            if hit_dt is not None:
                for r in list(before_w) + list(after_w):
                    row_dict = dict(r)
                    try:
                        msg_dt = _parse_iso(row_dict["date"])
                        if abs((msg_dt - hit_dt).total_seconds()) <= window_max_gap_min * 60:
                            valid_window_rows.append(row_dict)
                    except (ValueError, TypeError):
                        pass

        # 4. Merge, dedupe by id, sort chronologically, compute skipped_before
        all_candidates: dict[int, dict] = {}
        for r in thread_rows:
            if r["id"] in selected_thread_ids:
                all_candidates[r["id"]] = r
        for r in valid_window_rows:
            all_candidates[r["id"]] = r
        all_candidates[hit.message_id] = by_id[hit.message_id]

        sorted_msgs = [all_candidates[mid] for mid in sorted(all_candidates.keys())]
        included_ids = set(all_candidates.keys())
        all_thread_ids = [r["id"] for r in thread_rows]

        result: list[ContextMessage] = []
        for i, row in enumerate(sorted_msgs):
            mid = row["id"]
            prev_id = sorted_msgs[i - 1]["id"] if i > 0 else None
            skipped = sum(
                1 for tid in all_thread_ids
                if tid not in included_ids and (prev_id is None or tid > prev_id) and tid < mid
            )
            result.append(
                ContextMessage(
                    message_id=mid,
                    date=row["date"],
                    text=row["text"],
                    username=row["username"],
                    from_user_id=row["from_user_id"],
                    is_hit=(mid == hit.message_id),
                    chat_id=hit.chat_id,
                    reply_to_message_id=row.get("reply_to_message_id"),
                    skipped_before=skipped,
                )
            )

        return result

    def rebuild(self) -> int:
        """Rebuild FTS index from scratch. Returns count of indexed rows."""
        with self._conn() as c:
            c.execute("INSERT INTO messages_fts(messages_fts) VALUES ('rebuild')")
            c.commit()
            count = c.execute("SELECT COUNT(*) FROM messages_fts").fetchone()[0]
        return count
