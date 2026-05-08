# Phase 2 — Multi-Channel + Daemon

## Read first

This phase assumes Phase 1 has landed: `tgram/` package with Telethon-based ingest works for a single channel. Read [README.md](README.md) for stack context and [PHASE_1_bootstrap.md](PHASE_1_bootstrap.md) only if you need to understand existing structures.

## Goal

The user can configure a list of channels (or "all dialogs"), run `python -m tgram fetch_all`, and have every channel ingested. A daemon mode polls all enabled channels every N minutes via APScheduler.

## Prerequisites

- Phase 1 complete and verified (`fetch_new`, `fetch_gap`, `list_chan` work)
- A `data/messages.db` with the Phase 1 schema
- Telethon session authenticated (first-run prompt already done)

## New dependencies

Append to `requirements.txt`:
```text
apscheduler>=4.0.0
```

Note: APScheduler 4 is async-native and uses different APIs than v3. Use the v4 docs: https://apscheduler.readthedocs.io/

## Steps

### 1. Add `tgram/adapters/repo_channels.py`

```python
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from tgram.domain.channel import Channel


class ChannelRepo:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self.db_path)
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def upsert(self, ch: Channel) -> None:
        with self._conn() as c:
            c.execute(
                """INSERT INTO channels
                       (chat_id, title, type, is_forum,
                        last_fetched_id, oldest_fetched_id, last_fetch_at, enabled)
                   VALUES (?,?,?,?,?,?,?,?)
                   ON CONFLICT(chat_id) DO UPDATE SET
                       title=excluded.title,
                       type=excluded.type,
                       is_forum=excluded.is_forum""",
                (
                    ch.chat_id, ch.title, ch.type, int(ch.is_forum),
                    ch.last_fetched_id, ch.oldest_fetched_id,
                    ch.last_fetch_at.isoformat() if ch.last_fetch_at else None,
                    int(ch.enabled),
                ),
            )

    def update_progress(self, chat_id: int, last_fetched_id: int) -> None:
        with self._conn() as c:
            c.execute(
                """UPDATE channels SET
                       last_fetched_id = MAX(COALESCE(last_fetched_id, 0), ?),
                       last_fetch_at = ?
                   WHERE chat_id = ?""",
                (last_fetched_id, datetime.utcnow().isoformat(), chat_id),
            )

    def list_enabled(self) -> list[Channel]:
        with self._conn() as c:
            rows = c.execute("SELECT chat_id, title, type, is_forum, last_fetched_id, "
                             "oldest_fetched_id, last_fetch_at, enabled "
                             "FROM channels WHERE enabled = 1").fetchall()
        return [self._row(r) for r in rows]

    def list_all(self) -> list[Channel]:
        with self._conn() as c:
            rows = c.execute("SELECT chat_id, title, type, is_forum, last_fetched_id, "
                             "oldest_fetched_id, last_fetch_at, enabled FROM channels").fetchall()
        return [self._row(r) for r in rows]

    def get(self, chat_id: int) -> Channel | None:
        with self._conn() as c:
            row = c.execute("SELECT chat_id, title, type, is_forum, last_fetched_id, "
                            "oldest_fetched_id, last_fetch_at, enabled "
                            "FROM channels WHERE chat_id = ?", (chat_id,)).fetchone()
        return self._row(row) if row else None

    def set_enabled(self, chat_id: int, enabled: bool) -> None:
        with self._conn() as c:
            c.execute("UPDATE channels SET enabled = ? WHERE chat_id = ?",
                      (int(enabled), chat_id))

    @staticmethod
    def _row(r) -> Channel:
        return Channel(
            chat_id=r[0], title=r[1], type=r[2], is_forum=bool(r[3]),
            last_fetched_id=r[4], oldest_fetched_id=r[5],
            last_fetch_at=datetime.fromisoformat(r[6]) if r[6] else None,
            enabled=bool(r[7]),
        )
```

### 2. Extend `tgram/services/ingest.py`

Add multi-channel methods. The single-channel methods stay.

```python
class IngestService:
    def __init__(self, tg, repo_msg, repo_chan):
        self.tg = tg
        self.repo = repo_msg
        self.repo_chan = repo_chan

    # ... fetch_new / fetch_old / fetch_gap from Phase 1 ...

    async def refresh_dialogs(self) -> int:
        """Sync the channels table with the user's Telegram dialog list.
        Newly-discovered chats are added with enabled=False by default."""
        from tgram.domain.channel import Channel
        seen = 0
        existing = {c.chat_id for c in self.repo_chan.list_all()}
        for d in await self.tg.list_dialogs():
            ch = Channel(
                chat_id=d["chat_id"], title=d["title"], type=d["type"],
                is_forum=d["is_forum"], last_fetched_id=None,
                oldest_fetched_id=None, last_fetch_at=None,
                enabled=(d["chat_id"] in existing and self.repo_chan.get(d["chat_id"]).enabled)
                        or False,
            )
            self.repo_chan.upsert(ch)
            seen += 1
        return seen

    async def fetch_all_new(self) -> dict[int, int]:
        """Fetch new messages for every enabled channel.
        Returns {chat_id: count_saved}."""
        results = {}
        for ch in self.repo_chan.list_enabled():
            try:
                n = await self.fetch_new(ch.chat_id)
                if n > 0:
                    self.repo_chan.update_progress(ch.chat_id, self.repo.max_id(ch.chat_id))
                results[ch.chat_id] = n
            except Exception as e:
                import logging
                logging.getLogger(__name__).exception(
                    f"Failed fetching chat {ch.chat_id}: {e}")
                results[ch.chat_id] = -1
        return results
```

Update existing `fetch_new`/`fetch_old`/`fetch_gap` callers (CLI) to pass `repo_chan` when constructing `IngestService`.

### 3. Add `tgram/interfaces/daemon.py`

APScheduler 4 async loop. Single process. Restartable. Graceful shutdown on SIGINT/SIGTERM.

```python
import asyncio
import logging
import os
import signal

from apscheduler import AsyncScheduler
from apscheduler.triggers.interval import IntervalTrigger

from tgram.adapters.repo_channels import ChannelRepo
from tgram.adapters.repo_messages import MessageRepo
from tgram.adapters.telegram import TelegramClientAdapter
from tgram.config import Config
from tgram.services.ingest import IngestService

logger = logging.getLogger(__name__)


async def run_daemon():
    cfg = Config.load()
    interval_min = int(os.getenv("FETCH_INTERVAL_MINUTES", "5"))
    refresh_min = int(os.getenv("REFRESH_DIALOGS_MINUTES", "60"))

    repo_msg = MessageRepo(cfg.db_path)
    repo_chan = ChannelRepo(cfg.db_path)

    async with TelegramClientAdapter(cfg.api_id, cfg.api_hash, cfg.sessions_dir) as tg:
        svc = IngestService(tg, repo_msg, repo_chan)

        # Sync dialogs once at startup so the channels table is fresh.
        await svc.refresh_dialogs()
        logger.info("Initial dialog refresh complete")

        async with AsyncScheduler() as scheduler:
            await scheduler.add_schedule(
                svc.fetch_all_new,
                IntervalTrigger(minutes=interval_min),
                id="fetch_all_new",
            )
            await scheduler.add_schedule(
                svc.refresh_dialogs,
                IntervalTrigger(minutes=refresh_min),
                id="refresh_dialogs",
            )

            stop = asyncio.Event()
            for sig in (signal.SIGINT, signal.SIGTERM):
                asyncio.get_running_loop().add_signal_handler(sig, stop.set)

            logger.info(
                f"Daemon running: fetch every {interval_min}m, refresh every {refresh_min}m. "
                f"Press Ctrl+C to stop."
            )
            await scheduler.start_in_background()
            await stop.wait()
            logger.info("Shutting down daemon…")


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    asyncio.run(run_daemon())


if __name__ == "__main__":
    main()
```

### 4. Extend `tgram/interfaces/cli.py`

Add subcommands:

```python
sub.add_parser("fetch_all", help="Fetch new messages for every enabled channel")

ch_p = sub.add_parser("channels", help="Manage tracked channels")
ch_sub = ch_p.add_subparsers(dest="ch_cmd", required=True)
ch_sub.add_parser("list", help="List all known channels")
ch_sub.add_parser("refresh", help="Sync from Telegram dialogs")
ch_en = ch_sub.add_parser("enable", help="Mark channels as fetched-by-fetch_all")
ch_en.add_argument("chat_ids", nargs="+", type=int)
ch_dis = ch_sub.add_parser("disable", help="Stop fetching these channels")
ch_dis.add_argument("chat_ids", nargs="+", type=int)

sub.add_parser("daemon", help="Run scheduled poller")
```

Wire the handlers in `run()`:

```python
elif args.cmd == "fetch_all":
    async with TelegramClientAdapter(cfg.api_id, cfg.api_hash, cfg.sessions_dir) as tg:
        svc = IngestService(tg, repo, repo_chan)
        results = await svc.fetch_all_new()
    total = sum(n for n in results.values() if n >= 0)
    failed = [cid for cid, n in results.items() if n < 0]
    print(f"Saved {total} message(s) across {len(results)} channel(s). Failed: {len(failed)}")
    for cid in failed:
        print(f"  failed: {cid}")

elif args.cmd == "channels":
    if args.ch_cmd == "list":
        for ch in repo_chan.list_all():
            mark = "✓" if ch.enabled else "·"
            print(f"{mark} {ch.chat_id:>15}  {ch.type:<10}  {ch.title or ''}")
    elif args.ch_cmd == "refresh":
        async with TelegramClientAdapter(cfg.api_id, cfg.api_hash, cfg.sessions_dir) as tg:
            svc = IngestService(tg, repo, repo_chan)
            n = await svc.refresh_dialogs()
        print(f"Synced {n} dialog(s).")
    elif args.ch_cmd == "enable":
        for cid in args.chat_ids:
            repo_chan.set_enabled(cid, True)
        print(f"Enabled {len(args.chat_ids)} channel(s).")
    elif args.ch_cmd == "disable":
        for cid in args.chat_ids:
            repo_chan.set_enabled(cid, False)
        print(f"Disabled {len(args.chat_ids)} channel(s).")

elif args.cmd == "daemon":
    from tgram.interfaces.daemon import run_daemon
    await run_daemon()
```

`repo_chan = ChannelRepo(cfg.db_path)` is constructed once at top of `run()`.

### 5. `.env` additions

```text
FETCH_INTERVAL_MINUTES=5
REFRESH_DIALOGS_MINUTES=60
```

Update `env.template` accordingly. `CHAT_ID` (the Phase-1 default for single-channel commands) stays — `fetch_new` without `--chat` still uses it.

### 6. `docker-compose.yml` change

Daemon mode means a long-running container. Update the service:

```yaml
services:
  tgram:
    build: .
    container_name: tgram
    restart: unless-stopped
    volumes:
      - ./data:/app/data
    env_file: [.env]
    command: ["python", "-m", "tgram", "daemon"]
```

For one-shot CLI use, use `docker compose run --rm tgram <cmd>` (which overrides `command`). For the daemon: `docker compose up -d`.

## Acceptance criteria

1. **Channels table populated:**
   ```bash
   python -m tgram channels refresh
   python -m tgram channels list
   ```
   Lists every dialog the account has access to. Newly-added rows default to disabled.

2. **Selective enable/disable:**
   ```bash
   python -m tgram channels enable -1001234567890 -1009876543210
   python -m tgram channels list | grep '^✓'
   ```
   Only enabled channels show with `✓`.

3. **`fetch_all` only touches enabled channels:**
   - Run `python -m tgram fetch_all` after enabling a couple of channels.
   - Confirm it iterates only those, and `last_fetched_id` advances:
     ```bash
     sqlite3 data/messages.db "SELECT chat_id, last_fetched_id, last_fetch_at FROM channels WHERE enabled=1;"
     ```

4. **Daemon survives a fetch failure on one channel:**
   - Enable a channel you've left or that doesn't exist.
   - Start `python -m tgram daemon`.
   - Wait one cycle; daemon logs the failure but keeps running and other channels still get fetched.

5. **Daemon is interruptible:**
   - `Ctrl+C` in the daemon stops it within a few seconds with no traceback.

6. **Containerised daemon:**
   ```bash
   docker compose up -d tgram
   docker compose logs -f tgram
   ```
   Logs show periodic fetches. `docker compose down` stops cleanly.

7. **Idempotency under daemon restart:**
   - Stop and restart the daemon. The next cycle saves 0 new messages (already up to date).

## Out of scope

- Search (Phase 3)
- AI Q&A (Phase 4)
- Web UI (Phase 4)
- Per-channel custom intervals (single global interval is fine)

## Gotchas

- APScheduler 4 (`from apscheduler import AsyncScheduler`) is **not** the same as v3 (`from apscheduler.schedulers.asyncio import AsyncIOScheduler`). Many StackOverflow answers reference v3 — read v4 docs first.
- The Telethon client must stay alive for the duration of the daemon — that's why the scheduler runs **inside** the `async with TelegramClientAdapter(…) as tg:` block.
- Telethon respects FloodWait automatically. If you see warnings about FloodWait, that's normal — let it sleep.
- Channel IDs in Telegram are negative for groups/channels (e.g. `-1001234567890`). Make sure CLI `nargs="+"` accepts negative numbers — argparse needs `--` separator if the chat_id starts with `-`. Recommend documenting `python -m tgram channels enable -- -1001234567890` if necessary.
