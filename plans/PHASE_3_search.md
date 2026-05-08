# Phase 3 — Search (SQLite FTS5)

## Read first

This phase assumes Phase 2 has landed: multi-channel ingest works, `data/messages.db` has the canonical `messages` table with composite PK `(chat_id, id)`. Read [README.md](README.md) for stack context.

## Goal

The user can run `python -m tgram search "query string"` (and refine with `--chat`, `--since`, `--user`) and get ranked results from the entire archive in <100ms.

## Why FTS5

SQLite FTS5 is built into the SQLite stdlib, supports BM25 ranking, unicode tokenization, prefix matching, and stays in the same `messages.db` file. No new infrastructure.

## Steps

### 1. Add FTS5 schema

Create `tgram/migrations/003_fts5.sql`:

```sql
-- Contentless-mirror FTS5 virtual table over messages.text.
-- We use 'content=messages' so FTS reads from the base table; only the
-- text column is indexed but rowid lookups give us full row access.
CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
    text,
    content='messages',
    content_rowid='rowid',
    tokenize='unicode61 remove_diacritics 2'
);

-- Triggers to keep FTS index in sync with messages.
CREATE TRIGGER IF NOT EXISTS messages_ai AFTER INSERT ON messages
WHEN new.text IS NOT NULL
BEGIN
    INSERT INTO messages_fts (rowid, text) VALUES (new.rowid, new.text);
END;

CREATE TRIGGER IF NOT EXISTS messages_ad AFTER DELETE ON messages
BEGIN
    INSERT INTO messages_fts (messages_fts, rowid, text) VALUES('delete', old.rowid, old.text);
END;

CREATE TRIGGER IF NOT EXISTS messages_au AFTER UPDATE OF text ON messages
BEGIN
    INSERT INTO messages_fts (messages_fts, rowid, text) VALUES('delete', old.rowid, old.text);
    INSERT INTO messages_fts (rowid, text) VALUES (new.rowid, new.text);
END;

INSERT OR IGNORE INTO schema_version (version) VALUES (3);
```

### 2. Apply migration on startup

Update `MessageRepo._init_schema` in `tgram/adapters/repo_messages.py` to apply both `001_initial_schema.sql` and `003_fts5.sql`. Loop over the `migrations/` directory in lexical order, executing scripts whose numeric prefix is greater than the current `schema_version` (or simpler for now: `executescript()` both files; they are idempotent).

Note that `messages` table uses **`rowid`** for FTS linkage. SQLite assigns `rowid` automatically to non-WITHOUT-ROWID tables, even with a composite PK. Confirm with:
```sql
SELECT rowid, chat_id, id FROM messages LIMIT 5;
```

### 3. Backfill existing messages

For installations that already had messages before this phase: write a one-shot backfill in `tgram/migrations/004_fts_backfill.py`:

```python
"""Backfill FTS5 index from messages.text. Run once after Phase 3 schema lands."""
import sqlite3
from tgram.config import Config


def main():
    cfg = Config.load()
    with sqlite3.connect(cfg.db_path) as conn:
        conn.execute("INSERT INTO messages_fts (messages_fts) VALUES ('rebuild')")
        conn.commit()
    print("FTS5 index rebuilt.")


if __name__ == "__main__":
    main()
```

The `'rebuild'` command is an FTS5-builtin that re-derives the index from the content table.

### 4. `tgram/adapters/search_fts.py`

```python
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from tgram.domain.message import Message


@dataclass(frozen=True)
class SearchHit:
    message: Message
    score: float          # higher = more relevant (we negate BM25)
    snippet: str          # FTS5 snippet() output


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
        since: datetime | None = None,
        until: datetime | None = None,
        from_user_id: int | None = None,
        limit: int = 20,
    ) -> list[SearchHit]:
        # FTS5 query syntax: " quotes " for phrase, * for prefix.
        # We pass the raw user query through; the unicode61 tokenizer handles spacing.
        sql_parts = [
            "SELECT m.*, snippet(messages_fts, 0, '<<', '>>', '…', 12) AS snip, "
            "       bm25(messages_fts) AS bm25 "
            "FROM messages_fts "
            "JOIN messages m ON m.rowid = messages_fts.rowid "
            "WHERE messages_fts MATCH ?"
        ]
        params: list = [query]
        if chat_id is not None:
            sql_parts.append("AND m.chat_id = ?")
            params.append(chat_id)
        if since is not None:
            sql_parts.append("AND m.date >= ?")
            params.append(since.isoformat())
        if until is not None:
            sql_parts.append("AND m.date <= ?")
            params.append(until.isoformat())
        if from_user_id is not None:
            sql_parts.append("AND m.from_user_id = ?")
            params.append(from_user_id)
        sql_parts.append("ORDER BY bm25 LIMIT ?")
        params.append(limit)

        sql = " ".join(sql_parts)
        with self._conn() as c:
            rows = c.execute(sql, params).fetchall()

        hits = []
        for r in rows:
            msg = Message(
                chat_id=r["chat_id"], id=r["id"],
                date=datetime.fromisoformat(r["date"]),
                text=r["text"],
                from_user_id=r["from_user_id"], username=r["username"],
                reply_to_message_id=r["reply_to_message_id"],
                reply_to_top_message_id=r["reply_to_top_message_id"],
                virtual_topic_id=r["virtual_topic_id"],
                media_type=r["media_type"], raw_json=r["raw_json"],
            )
            hits.append(SearchHit(message=msg, score=-r["bm25"], snippet=r["snip"]))
        return hits
```

Notes:
- `bm25()` returns lower = more relevant in FTS5; we negate to make `score` "higher = better" for downstream use.
- `snippet(table, col, start, end, ellipsis, tokens)` — column 0 is the indexed column; 12 tokens of context is a good default.

### 5. `tgram/services/search.py`

```python
from datetime import datetime, timedelta

from tgram.adapters.search_fts import FTSSearch, SearchHit


class SearchService:
    def __init__(self, fts: FTSSearch):
        self.fts = fts

    def search(
        self,
        query: str,
        *,
        chat_id: int | None = None,
        since_hours: float | None = None,
        from_user_id: int | None = None,
        limit: int = 20,
    ) -> list[SearchHit]:
        since = datetime.utcnow() - timedelta(hours=since_hours) if since_hours else None
        return self.fts.search(
            query,
            chat_id=chat_id, since=since,
            from_user_id=from_user_id, limit=limit,
        )
```

### 6. CLI subcommand

Extend `tgram/interfaces/cli.py`:

```python
sp = sub.add_parser("search", help="Full-text search the archive")
sp.add_argument("query", help="FTS5 query (use \"phrase\" for phrase search, term* for prefix)")
sp.add_argument("--chat", type=int, default=None)
sp.add_argument("--since-hours", type=float, default=None)
sp.add_argument("--user", type=int, default=None, help="from_user_id")
sp.add_argument("--limit", type=int, default=20)
```

Handler:

```python
elif args.cmd == "search":
    from tgram.adapters.search_fts import FTSSearch
    from tgram.services.search import SearchService
    svc = SearchService(FTSSearch(cfg.db_path))
    hits = svc.search(
        args.query, chat_id=args.chat,
        since_hours=args.since_hours,
        from_user_id=args.user, limit=args.limit,
    )
    if not hits:
        print("(no matches)")
        return 0
    for h in hits:
        m = h.message
        when = m.date.strftime("%Y-%m-%d %H:%M")
        who = m.username or (str(m.from_user_id) if m.from_user_id else "anon")
        print(f"[{when}] {m.chat_id}/{m.id} @{who}  {h.snippet}")
```

### 7. Hybrid retrieval helper (used by Phase 4)

Add `tgram/services/retrieval.py` now, even though no LLM is wired yet — Phase 4 will plug into this.

```python
from dataclasses import dataclass

from tgram.adapters.search_fts import FTSSearch, SearchHit


@dataclass(frozen=True)
class RetrievalResult:
    hits: list[SearchHit]
    method: str   # "fts" | "vector" | "hybrid"


class Retriever:
    """Phase 3: FTS-only. Phase 4 expands this to hybrid (FTS + vector)."""

    def __init__(self, fts: FTSSearch):
        self.fts = fts

    def retrieve(self, query: str, *, chat_id: int | None = None,
                 limit: int = 50) -> RetrievalResult:
        hits = self.fts.search(query, chat_id=chat_id, limit=limit)
        return RetrievalResult(hits=hits, method="fts")
```

## Acceptance criteria

1. **Schema present:**
   ```bash
   sqlite3 data/messages.db ".schema messages_fts"
   ```
   Shows the FTS5 virtual table.

2. **Triggers fire on new ingest:**
   - Run `python -m tgram fetch_new` and capture initial FTS row count:
     ```bash
     sqlite3 data/messages.db "SELECT COUNT(*) FROM messages_fts"
     ```
   - Re-run a manual count of `SELECT COUNT(*) FROM messages WHERE text IS NOT NULL` — must match.

3. **Backfill works for pre-existing data:**
   ```bash
   python -m tgram.migrations.004_fts_backfill
   sqlite3 data/messages.db "SELECT COUNT(*) FROM messages_fts"
   ```
   Count matches non-null text rows.

4. **Search returns ranked results:**
   ```bash
   python -m tgram search "telegram"
   ```
   Returns up to 20 messages mentioning "telegram", most relevant first.

5. **Phrase + prefix search:**
   ```bash
   python -m tgram search '"exact phrase here"'
   python -m tgram search 'tele*'
   ```
   Both work; prefix matches words starting with "tele".

6. **Filters apply:**
   ```bash
   python -m tgram search "release" --chat <CHAT_ID> --since-hours 168 --limit 5
   ```
   Only returns messages from that chat in the last week.

7. **Performance sanity:**
   ```bash
   time python -m tgram search "anything"
   ```
   <500ms even on a million-row archive (the SQL itself takes <50ms; the rest is Python startup).

8. **Unicode/multilingual:**
   - Search a Cyrillic word that you know exists in stored messages (e.g. "привет"). Returns matches.

## Out of scope

- Vector / semantic search (Phase 4)
- LLM Q&A (Phase 4)
- Highlighting in the CLI beyond `<<…>>` snippets
- Saved-search / search-history features

## Gotchas

- **Composite PK + FTS5:** The `messages` table has composite PK `(chat_id, id)`, but SQLite still assigns an internal `rowid` because the table is not declared `WITHOUT ROWID`. FTS5 `content_rowid='rowid'` works because of this. **Do not** convert `messages` to `WITHOUT ROWID` — it would break FTS5 linkage.
- **NULL text:** Trigger `messages_ai` has `WHEN new.text IS NOT NULL` to skip media-only messages. Don't remove this — inserting NULL into FTS5 produces empty rows that still cost index space.
- **Special characters in query:** FTS5 query syntax treats `-`, `:`, `^`, etc. as operators. If the user's literal query needs them, they must double-quote: `python -m tgram search '"foo-bar"'`.
- **bm25 ordering direction:** FTS5's `bm25()` returns negative numbers; lower (more negative) = more relevant. We `ORDER BY bm25` ascending and negate when returning the score upward.
