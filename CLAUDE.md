# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Setup

Copy `env.template` to `.env`:

```env
API_ID=your_api_id
API_HASH=your_api_hash
CHAT_ID=your_default_chat_id   # used when --chat flag is omitted
BATCH_SIZE=200
OUTPUT_DIR=./data
FETCH_INTERVAL_MINUTES=5
REFRESH_DIALOGS_MINUTES=60
```

Credentials from [my.telegram.org](https://my.telegram.org) → API Development Tools.

## Running

```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt

# One-off commands
.venv/bin/python -m tgram list_chan
.venv/bin/python -m tgram fetch_new --chat -1001593560584
.venv/bin/python -m tgram fetch_old --chat -1001593560584 --loop
.venv/bin/python -m tgram fetch_gap 1000 2000 --chat -1001593560584
.venv/bin/python -m tgram fetch_scan --chat -1001593560584
.venv/bin/python -m tgram status --chat -1001593560584

# Topic management
.venv/bin/python -m tgram sync_topics --chat -1001593560584
.venv/bin/python -m tgram list_topics --chat -1001593560584

# Multi-channel
.venv/bin/python -m tgram channels refresh
.venv/bin/python -m tgram channels list
.venv/bin/python -m tgram channels enable -- -1001593560584 -1001919096489
.venv/bin/python -m tgram fetch_all

# Search
.venv/bin/python -m tgram rebuild_fts           # run once after first install
.venv/bin/python -m tgram search "query"
.venv/bin/python -m tgram search "query" --context 3 --topic 1872

# Daemon (keeps all enabled channels up to date)
.venv/bin/python -m tgram daemon
```

## Architecture

The app is a `tgram/` Python package. Entry point: `python -m tgram <cmd>`.

**Layers (strict — no cross-layer imports except downward):**

```
interfaces/   cli.py, daemon.py          — arg parsing, output, scheduling
services/     ingest.py, search.py       — use-case orchestration, no I/O directly
adapters/     telegram.py, repo_*.py,    — Telethon, SQLite, FTS5
              search_fts.py
domain/       message.py, channel.py,    — frozen dataclasses, zero I/O
              topic.py
migrations/   001_*.sql, 002_*.sql …     — applied in sorted order on every startup
```

**Data flow — ingest:**
1. `TelegramClientAdapter.iter_history()` yields `Message` domain objects from Telethon
2. `IngestService._stream_and_save()` buffers 500 messages, calls `MessageRepo.save_many()` per batch
3. `IngestService._set_virtual_topic()` walks `reply_to_message_id` chain via `MessageRepo.reply_root()` and stamps `virtual_topic_id` on each message before saving
4. FTS5 INSERT trigger on `messages` table auto-indexes new text

**Data flow — search:**
1. `FTSSearch.search()` runs FTS5 MATCH query, joins `messages` + `topics`, returns `SearchHit` list with BM25 snippet
2. `FTSSearch.get_context()` fetches surrounding messages in the same topic thread

**SQLite schema (3 migration files so far):**
- `messages` — composite PK `(chat_id, id)`, stores full `raw_json` plus typed columns; indexes on `date`, `from_user_id`, `reply_to_top_message_id`, `virtual_topic_id`
- `channels` — per-channel state: `last_fetched_id`, `enabled`, `is_forum`
- `topics` — maps `(chat_id, topic_id)` → `title` (fetched from Telegram `MessageService` objects)
- `messages_fts` — FTS5 virtual table with content mirror; keep-sync triggers on INSERT/UPDATE/DELETE

**Topic system:**
- *Native topics*: `reply_to_top_message_id` — set by Telegram for forum-type channels. Populated during ingest via `TelegramClientAdapter._convert()` (handles the edge case where `reply_to_top_id` is null when replying directly to the topic root).
- *Virtual topics*: `virtual_topic_id` — reply-chain root, computed locally by walking `reply_to_message_id` up to the first message with no parent.

**Session management:** Telethon session stored at `data/sessions/tgram.session`. First run prompts for phone + SMS code interactively. Subsequent runs use the stored session silently.

**Daemon:** `interfaces/daemon.py` runs a plain `asyncio` sleep loop — no external scheduler. Polls enabled channels every `FETCH_INTERVAL_MINUTES`, refreshes dialog list every `REFRESH_DIALOGS_MINUTES`. Handles SIGINT/SIGTERM cleanly.

## Key known issues / not yet implemented

- `fetch_scan` shows real gaps but `fetch_gap` must be called manually to fill them — no auto-fill
- Phase 4 (AI Q&A: embeddings, LiteLLM, Gradio UI) not yet implemented — see `plans/PHASE_4_ai_qa.md`
- `nomic-embed-text-v2-moe:latest` and `qwen3.6:35b-a3b-q4_k_m` are already pulled in Ollama, ready for Phase 4
