# Phase 1 — Bootstrap (Fresh Project + Telethon Ingest)

## Read first

This phase **rewrites the project from scratch** in the same git repo. The old code in `main.py`, `fetcher/`, and `config.py` is deleted (a backup branch is made first). A pre-existing `data/messages.db` is preserved and migrated into the new schema.

Read [README.md](README.md) in this directory for the locked-in tool stack and target architecture before starting.

## Goal

A new project layout where the user can run `python -m tgram fetch_new` against a single Telegram channel and have messages saved into a fresh SQLite schema. No multi-channel, no search, no AI yet — just a clean foundation built on Telethon.

## Prerequisites

- Python 3.11+
- A `.env` file with `API_ID`, `API_HASH`, `CHAT_ID` (single channel for now), `BATCH_SIZE`, `OUTPUT_DIR`
- Ollama running locally (Phase 4 needs it; not required this phase)
- Local Ollama models already pulled: `qwen3.6:35b-a3b-q4_k_m`, `nomic-embed-text-v2-moe:latest`
- A Telegram account with active membership in at least one test channel

## Steps

### 1. Backup and clean

```bash
git checkout -b pre-rewrite-backup
git checkout -
git checkout -b rewrite-phase-1
git rm -r main.py fetcher/ config.py
```

Keep on disk: `data/messages.db` (legacy data), `data/sessions/` (Pyrogram session — will be unused but safe to keep), `Dockerfile`, `docker-compose.yml`, `tgram.sh`, `requirements.txt`, `env.template`, `docs/`, `README.md`, `plans/`, `.env`, `.gitignore`.

### 2. Create directory layout

```
tgram/
├── __init__.py
├── __main__.py
├── config.py
├── domain/
│   ├── __init__.py
│   ├── message.py
│   └── channel.py
├── adapters/
│   ├── __init__.py
│   ├── telegram.py
│   └── repo_messages.py
├── services/
│   ├── __init__.py
│   └── ingest.py
├── interfaces/
│   ├── __init__.py
│   └── cli.py
└── migrations/
    ├── 001_initial_schema.sql
    └── 002_import_legacy.py
```

`__main__.py` allows `python -m tgram <cmd>`. The single top-level `tgram/` package replaces the old scattered files.

### 3. Update `requirements.txt`

```text
telethon>=1.36.0
python-dotenv>=1.0.0
# Phase-2+ deps are added later, not now
```

Drop pyrogram, tgcrypto, asyncio-mqtt, uvloop. They are no longer needed.

### 4. `tgram/config.py`

Loads `.env`, validates required keys, returns a frozen dataclass.

```python
import os
from dataclasses import dataclass
from pathlib import Path
from dotenv import load_dotenv


@dataclass(frozen=True)
class Config:
    api_id: int
    api_hash: str
    default_chat_id: int          # used when no --chat is given
    batch_size: int
    data_dir: Path
    db_path: Path
    sessions_dir: Path

    @classmethod
    def load(cls) -> "Config":
        load_dotenv()
        required = ["API_ID", "API_HASH", "CHAT_ID"]
        for k in required:
            if not os.getenv(k):
                raise RuntimeError(f"Missing required env var: {k}")
        data_dir = Path(os.getenv("OUTPUT_DIR", "./data"))
        data_dir.mkdir(parents=True, exist_ok=True)
        sessions = data_dir / "sessions"
        sessions.mkdir(parents=True, exist_ok=True)
        return cls(
            api_id=int(os.getenv("API_ID")),
            api_hash=os.getenv("API_HASH"),
            default_chat_id=int(os.getenv("CHAT_ID")),
            batch_size=int(os.getenv("BATCH_SIZE", "100")),
            data_dir=data_dir,
            db_path=data_dir / "messages.db",
            sessions_dir=sessions,
        )
```

### 5. `tgram/domain/message.py`

```python
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Message:
    chat_id: int
    id: int
    date: datetime
    text: str | None
    from_user_id: int | None
    username: str | None
    reply_to_message_id: int | None
    reply_to_top_message_id: int | None   # native forum topic
    virtual_topic_id: int | None          # reply-chain root
    media_type: str | None
    raw_json: str                         # full JSON dump for forensics
```

### 6. `tgram/domain/channel.py`

```python
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Channel:
    chat_id: int
    title: str | None
    type: str                 # "channel" | "supergroup" | "group" | "private"
    is_forum: bool
    last_fetched_id: int | None
    oldest_fetched_id: int | None
    last_fetch_at: datetime | None
    enabled: bool
```

(The `channels` table is fully exercised in Phase 2; Phase 1 only writes a row when first ingesting a chat.)

### 7. `tgram/migrations/001_initial_schema.sql`

```sql
CREATE TABLE IF NOT EXISTS messages (
    chat_id                 INTEGER NOT NULL,
    id                      INTEGER NOT NULL,
    date                    TEXT NOT NULL,
    text                    TEXT,
    from_user_id            INTEGER,
    username                TEXT,
    reply_to_message_id     INTEGER,
    reply_to_top_message_id INTEGER,
    virtual_topic_id        INTEGER,
    media_type              TEXT,
    raw_json                TEXT NOT NULL,
    created_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (chat_id, id)
);

CREATE INDEX IF NOT EXISTS idx_messages_date          ON messages(date);
CREATE INDEX IF NOT EXISTS idx_messages_user          ON messages(from_user_id);
CREATE INDEX IF NOT EXISTS idx_messages_native_topic  ON messages(chat_id, reply_to_top_message_id);
CREATE INDEX IF NOT EXISTS idx_messages_virtual_topic ON messages(chat_id, virtual_topic_id);
CREATE INDEX IF NOT EXISTS idx_messages_reply         ON messages(chat_id, reply_to_message_id);

CREATE TABLE IF NOT EXISTS channels (
    chat_id            INTEGER PRIMARY KEY,
    title              TEXT,
    type               TEXT NOT NULL,
    is_forum           INTEGER NOT NULL DEFAULT 0,
    last_fetched_id    INTEGER,
    oldest_fetched_id  INTEGER,
    last_fetch_at      TIMESTAMP,
    enabled            INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY,
    applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
INSERT OR IGNORE INTO schema_version (version) VALUES (1);
```

### 8. `tgram/adapters/repo_messages.py`

```python
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from datetime import datetime

from tgram.domain.message import Message


SCHEMA_PATH = Path(__file__).parent.parent / "migrations" / "001_initial_schema.sql"


class MessageRepo:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _init_schema(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.executescript(SCHEMA_PATH.read_text())

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self.db_path)
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def save(self, msg: Message) -> None:
        with self._conn() as c:
            c.execute(
                """INSERT OR REPLACE INTO messages
                   (chat_id, id, date, text, from_user_id, username,
                    reply_to_message_id, reply_to_top_message_id,
                    virtual_topic_id, media_type, raw_json)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    msg.chat_id, msg.id,
                    msg.date.isoformat(),
                    msg.text, msg.from_user_id, msg.username,
                    msg.reply_to_message_id, msg.reply_to_top_message_id,
                    msg.virtual_topic_id, msg.media_type, msg.raw_json,
                ),
            )

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

    def find_gaps(self, chat_id: int) -> list[tuple[int, int]]:
        with self._conn() as c:
            ids = [r[0] for r in c.execute(
                "SELECT id FROM messages WHERE chat_id=? ORDER BY id", (chat_id,)
            )]
        gaps = []
        for i in range(1, len(ids)):
            if ids[i] > ids[i-1] + 1:
                gaps.append((ids[i-1] + 1, ids[i] - 1))
        return gaps

    def reply_root(self, chat_id: int, message_id: int) -> int:
        """Walk up reply_to_message_id to root. Returns input id if no chain."""
        current = message_id
        seen = set()
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
        return current
```

### 9. `tgram/adapters/telegram.py`

Telethon wrapper that yields `Message` domain objects. Handles session, FloodWait, message conversion.

```python
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import AsyncIterator

from telethon import TelegramClient
from telethon.errors import FloodWaitError
from telethon.tl.custom.message import Message as TLMessage

from tgram.domain.message import Message

logger = logging.getLogger(__name__)


class TelegramClientAdapter:
    def __init__(self, api_id: int, api_hash: str, sessions_dir: Path):
        self.api_id = api_id
        self.api_hash = api_hash
        self.session_path = str(sessions_dir / "tgram")
        self._client: TelegramClient | None = None

    async def __aenter__(self):
        self._client = TelegramClient(self.session_path, self.api_id, self.api_hash)
        await self._client.start()  # prompts for phone+code first run
        return self

    async def __aexit__(self, *exc):
        if self._client:
            await self._client.disconnect()

    @property
    def client(self) -> TelegramClient:
        assert self._client is not None, "Use as async context manager"
        return self._client

    async def iter_history(
        self,
        chat_id: int,
        *,
        min_id: int = 0,
        max_id: int = 0,
        limit: int | None = None,
    ) -> AsyncIterator[Message]:
        """Iterate messages for a chat, newest first.
        min_id: only messages with id > min_id (0 = no lower bound)
        max_id: only messages with id < max_id (0 = no upper bound)
        """
        try:
            async for tlm in self.client.iter_messages(
                chat_id, min_id=min_id, max_id=max_id, limit=limit
            ):
                if tlm is None:
                    continue
                yield self._convert(chat_id, tlm)
        except FloodWaitError as e:
            logger.warning(f"FloodWait {e.seconds}s — Telethon will sleep & retry")
            raise

    async def get_messages_by_ids(self, chat_id: int, ids: list[int]) -> list[Message]:
        result = []
        for tlm in await self.client.get_messages(chat_id, ids=ids):
            if tlm is None or getattr(tlm, "empty", False):
                continue
            result.append(self._convert(chat_id, tlm))
        return result

    async def list_dialogs(self) -> list[dict]:
        """Used by Phase 2 to populate channels table."""
        out = []
        async for d in self.client.iter_dialogs():
            out.append({
                "chat_id": d.id,
                "title": d.title,
                "type": "channel" if d.is_channel else ("group" if d.is_group else "private"),
                "is_forum": getattr(d.entity, "forum", False),
            })
        return out

    @staticmethod
    def _convert(chat_id: int, tlm: TLMessage) -> Message:
        sender = tlm.sender
        media_type = type(tlm.media).__name__ if tlm.media else None
        # Telethon native topic id (forum):
        reply = tlm.reply_to
        native_topic = getattr(reply, "reply_to_top_id", None) if reply else None
        reply_to_id  = getattr(reply, "reply_to_msg_id", None) if reply else None
        return Message(
            chat_id=chat_id,
            id=tlm.id,
            date=tlm.date,
            text=tlm.message,
            from_user_id=getattr(sender, "id", None) if sender else None,
            username=getattr(sender, "username", None) if sender else None,
            reply_to_message_id=reply_to_id,
            reply_to_top_message_id=native_topic,
            virtual_topic_id=None,  # populated by service layer
            media_type=media_type,
            raw_json=tlm.to_json(),
        )
```

### 10. `tgram/services/ingest.py`

The service layer composes adapters. It does NOT import telethon or sqlite3 directly.

```python
import logging

from tgram.adapters.repo_messages import MessageRepo
from tgram.adapters.telegram import TelegramClientAdapter
from tgram.domain.message import Message

logger = logging.getLogger(__name__)


class IngestService:
    def __init__(self, tg: TelegramClientAdapter, repo: MessageRepo):
        self.tg = tg
        self.repo = repo

    async def fetch_new(self, chat_id: int) -> int:
        """Fetch messages with id > max_stored_id. Returns count saved."""
        since = self.repo.max_id(chat_id) or 0
        logger.info(f"fetch_new chat={chat_id} since_id={since}")
        saved = 0
        async for msg in self.tg.iter_history(chat_id, min_id=since):
            if self.repo.exists(chat_id, msg.id):
                continue
            self._enrich_topic(msg)
            self.repo.save(msg)
            saved += 1
        return saved

    async def fetch_old(self, chat_id: int, limit: int | None = None) -> int:
        oldest = self.repo.min_id(chat_id) or 0
        max_id = oldest if oldest else 0
        saved = 0
        async for msg in self.tg.iter_history(chat_id, max_id=max_id, limit=limit):
            if self.repo.exists(chat_id, msg.id):
                continue
            self._enrich_topic(msg)
            self.repo.save(msg)
            saved += 1
        return saved

    async def fetch_gap(self, chat_id: int, start_id: int, end_id: int) -> int:
        if start_id > end_id:
            raise ValueError("start_id must be <= end_id")
        saved = 0
        # get_messages allows lists up to 100 ids per call in Telethon
        CHUNK = 100
        for s in range(start_id, end_id + 1, CHUNK):
            ids = list(range(s, min(s + CHUNK, end_id + 1)))
            for msg in await self.tg.get_messages_by_ids(chat_id, ids):
                if self.repo.exists(chat_id, msg.id):
                    continue
                self._enrich_topic(msg)
                self.repo.save(msg)
                saved += 1
        return saved

    def _enrich_topic(self, msg: Message) -> None:
        # Cannot mutate frozen dataclass; service rebuilds with virtual_topic_id.
        # Use object.__setattr__ since Message is frozen.
        if msg.reply_to_message_id:
            root = self.repo.reply_root(msg.chat_id, msg.reply_to_message_id)
        else:
            root = msg.id
        object.__setattr__(msg, "virtual_topic_id", root)
```

### 11. `tgram/interfaces/cli.py`

```python
import argparse
import asyncio
import logging

from tgram.adapters.repo_messages import MessageRepo
from tgram.adapters.telegram import TelegramClientAdapter
from tgram.config import Config
from tgram.services.ingest import IngestService


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="tgram")
    sub = p.add_subparsers(dest="cmd", required=True)

    f_new = sub.add_parser("fetch_new", help="Fetch newest messages")
    f_new.add_argument("--chat", type=int, default=None)

    f_old = sub.add_parser("fetch_old", help="Fetch older messages")
    f_old.add_argument("--chat", type=int, default=None)
    f_old.add_argument("--limit", type=int, default=None)

    f_gap = sub.add_parser("fetch_gap", help="Fetch a specific ID range")
    f_gap.add_argument("start", type=int)
    f_gap.add_argument("end", type=int)
    f_gap.add_argument("--chat", type=int, default=None)

    f_scan = sub.add_parser("fetch_scan", help="Show gaps in stored messages")
    f_scan.add_argument("--chat", type=int, default=None)

    f_status = sub.add_parser("status", help="Show storage stats")
    f_status.add_argument("--chat", type=int, default=None)

    sub.add_parser("list_chan", help="List dialogs you have access to")

    return p


async def run(args) -> int:
    cfg = Config.load()
    repo = MessageRepo(cfg.db_path)
    chat_id = getattr(args, "chat", None) or cfg.default_chat_id

    if args.cmd == "fetch_scan":
        gaps = repo.find_gaps(chat_id)
        if not gaps:
            print(f"No gaps in chat {chat_id}.")
        else:
            print(f"{len(gaps)} gap(s) in chat {chat_id}:")
            for s, e in gaps:
                print(f"  {s}-{e}  ({e-s+1} msgs)")
        return 0

    if args.cmd == "status":
        mn = repo.min_id(chat_id)
        mx = repo.max_id(chat_id)
        gaps = repo.find_gaps(chat_id)
        print(f"chat {chat_id}: id range {mn}-{mx}, {len(gaps)} gaps")
        return 0

    async with TelegramClientAdapter(cfg.api_id, cfg.api_hash, cfg.sessions_dir) as tg:
        svc = IngestService(tg, repo)
        if args.cmd == "fetch_new":
            n = await svc.fetch_new(chat_id)
            print(f"Saved {n} new message(s).")
        elif args.cmd == "fetch_old":
            n = await svc.fetch_old(chat_id, limit=args.limit)
            print(f"Saved {n} older message(s).")
        elif args.cmd == "fetch_gap":
            n = await svc.fetch_gap(chat_id, args.start, args.end)
            print(f"Saved {n} message(s) in gap {args.start}-{args.end}.")
        elif args.cmd == "list_chan":
            for d in await tg.list_dialogs():
                forum = " [forum]" if d["is_forum"] else ""
                print(f"{d['chat_id']:>15}  {d['type']:<10}  {d['title']}{forum}")
    return 0


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    args = build_parser().parse_args()
    return asyncio.run(run(args))
```

### 12. `tgram/__main__.py`

```python
from tgram.interfaces.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
```

### 13. `tgram/migrations/002_import_legacy.py`

Imports rows from the old `messages` table (if present) into the new schema. Old schema had a single PK `id` column; new schema has composite `(chat_id, id)`. Old rows' `chat_id` is read from the column they already had.

```python
"""Run once after Phase 1 lands to bring legacy messages into new schema.

Usage: python -m tgram.migrations.002_import_legacy
"""
import json
import logging
import sqlite3
from pathlib import Path

from tgram.config import Config

logger = logging.getLogger(__name__)


def main():
    cfg = Config.load()
    legacy = cfg.db_path
    if not legacy.exists():
        print("No legacy DB to migrate.")
        return

    backup = legacy.with_suffix(".legacy-backup.db")
    if not backup.exists():
        backup.write_bytes(legacy.read_bytes())
        print(f"Backup created: {backup}")

    with sqlite3.connect(legacy) as conn:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(messages)")]
        if "raw_data" not in cols:
            print("No legacy 'raw_data' column — nothing to migrate.")
            return

        conn.execute("""CREATE TEMP TABLE _legacy AS
                        SELECT id, chat_id, raw_data FROM messages WHERE raw_data IS NOT NULL""")
        rows = conn.execute("SELECT id, chat_id, raw_data FROM _legacy").fetchall()
        print(f"Importing {len(rows)} legacy rows…")

        for old_id, chat_id, raw in rows:
            data = json.loads(raw)
            conn.execute(
                """INSERT OR IGNORE INTO messages
                   (chat_id, id, date, text, from_user_id, username,
                    reply_to_message_id, reply_to_top_message_id,
                    virtual_topic_id, media_type, raw_json)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    chat_id or data.get("chat_id"),
                    old_id,
                    data.get("date"),
                    data.get("text"),
                    (data.get("from_user") or {}).get("id"),
                    (data.get("from_user") or {}).get("username"),
                    data.get("reply_to_message_id"),
                    data.get("reply_to_top_message_id"),
                    None,                        # virtual topic — recomputed later
                    data.get("media"),
                    raw,
                ),
            )
        conn.commit()
    print("Migration complete. Run `python -m tgram fetch_new` to resume.")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
```

### 14. Update `tgram.sh`

Replace contents with thin wrapper that invokes the new module:

```bash
#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
exec python -m tgram "$@"
```

(Docker support is unchanged — `docker-compose.yml` already mounts `data/` and `sessions/`. The Dockerfile's `CMD ["python", "main.py"]` should change to `CMD ["python", "-m", "tgram"]`.)

### 15. Update `Dockerfile` `CMD`

Change the final line from `CMD ["python", "main.py"]` to `CMD ["python", "-m", "tgram"]`. Telethon does not need a special build step or system packages beyond what Pyrogram had.

### 16. `.gitignore` additions (if missing)

```
data/messages.db
data/messages.legacy-backup.db
data/sessions/
.env
__pycache__/
*.pyc
```

## Acceptance criteria

Run from project root after implementation:

1. **Imports clean:**
   ```bash
   python -c "from tgram.interfaces.cli import build_parser; build_parser().parse_args(['--help'])"
   ```
   Must print help text and exit 0.

2. **Schema applies:**
   ```bash
   rm -f data/messages.db
   python -c "from tgram.adapters.repo_messages import MessageRepo; from tgram.config import Config; MessageRepo(Config.load().db_path)"
   sqlite3 data/messages.db ".schema messages"
   ```
   Must show the schema with composite PK `(chat_id, id)`.

3. **First run authenticates:**
   ```bash
   python -m tgram list_chan
   ```
   Prompts for phone + code on first run, then prints dialogs.

4. **`fetch_new` works end-to-end:**
   ```bash
   python -m tgram fetch_new --chat <CHAT_ID>
   ```
   Saves N messages. Re-running saves 0 (idempotent).

5. **Virtual topics populated:**
   ```bash
   sqlite3 data/messages.db "SELECT COUNT(*) FROM messages WHERE virtual_topic_id IS NULL;"
   ```
   Must return 0.

6. **Gap fetch works:**
   - Pick an empty range like `<min_id-100>` to `<min_id-50>`:
     ```bash
     python -m tgram fetch_gap <start> <end> --chat <CHAT_ID>
     sqlite3 data/messages.db "SELECT COUNT(*) FROM messages WHERE chat_id=<CHAT_ID> AND id BETWEEN <start> AND <end>;"
     ```
   - Count > 0 (excluding deleted IDs).

7. **Legacy migration (if `data/messages.db` from old codebase existed before Step 1):**
   ```bash
   python -m tgram.migrations.002_import_legacy
   ```
   Backup file `data/messages.legacy-backup.db` is created. New schema rows are populated. No errors.

8. **`fetch_scan` reports real gaps:**
   ```bash
   python -m tgram fetch_scan --chat <CHAT_ID>
   ```
   Output matches manual SQL gap query:
   ```bash
   sqlite3 data/messages.db "SELECT id FROM messages WHERE chat_id=<CHAT_ID> ORDER BY id" \
     | awk 'NR>1 && $1 != prev+1 { print prev+1 "-" $1-1 } { prev=$1 }'
   ```

## Out of scope

- `channels` table is created but not yet used (Phase 2 fills it).
- Multi-channel `fetch_all` (Phase 2).
- Daemon mode / scheduler (Phase 2).
- FTS5 / search / vectors / AI (Phases 3–4).
- Tests (defer to Phase 2 or 3 — current foundation needs to settle first).

## Key gotchas for the implementer

- `Message` is frozen; Phase 1 uses `object.__setattr__` to set `virtual_topic_id` post-construction. Cleaner alternative: build Message without `virtual_topic_id` first, then create a new Message with it. Either is fine.
- Telethon's first run needs an interactive phone-code prompt. Keep `stdin_open: true` and `tty: true` in `docker-compose.yml`.
- Telethon's `iter_messages` natively respects FloodWait — no manual sleep needed.
- When `text` is None (media-only messages), the column stores NULL — that's expected.
- Telethon stores its session in a `.session` SQLite file at `sessions_dir/tgram.session`. This is **not** the same format as the old Pyrogram session — first auth is unavoidable.
