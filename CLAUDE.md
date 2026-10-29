# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Setup

Copy `env.template` to `.env`:

```env
API_ID=your_api_id
API_HASH=your_api_hash
CHAT_ID=your_default_chat_id   # used by make targets and when --chat is omitted
FETCH_INTERVAL_MINUTES=5
REFRESH_DIALOGS_MINUTES=60
GEMINI_API_KEY=...
ANTHROPIC_API_KEY=...
OPENAI_API_KEY=...
```

Credentials from [my.telegram.org](https://my.telegram.org) → API Development Tools.

## Running

Prefer `make` targets — they use `CHAT_ID` from `.env` automatically:

```bash
make fetch-new
make embed
make daemon
make repair-threads
make thread ID=12345
make ask Q="how do I open a company in Poland"
make search Q="карта резидента"
make web
```

Or use `.venv/bin/python -m tgram <cmd>` directly. Full command list in README.md.

## Architecture

The app is a `tgram/` Python package. Entry point: `python -m tgram <cmd>`.

**Layers (strict — imports only flow downward):**

```
interfaces/   cli.py, daemon.py, web.py  — arg parsing, output, Gradio UI
services/     ingest.py, search.py,      — use-case orchestration, no I/O directly
              ai.py, embed.py
adapters/     telegram.py, repo_*.py,    — Telethon, SQLite, FTS5, sqlite-vec
              search_fts.py,
              llm_ollama.py, llm_litellm.py,
              repo_embeddings.py
domain/       message.py, channel.py,    — frozen dataclasses, zero I/O
              topic.py, threading.py
migrations/   001_*.sql … 005_*.sql      — applied in sorted order on every startup
```

**Data flow — ingest:**
1. `TelegramClientAdapter.iter_history()` yields `Message` domain objects from Telethon (`reverse=True` oldest-first on `fetch_new` to avoid gaps below `max_id`).
2. `IngestService._stream_and_save()` buffers messages, calls `MessageRepo.save_many()` per batch.
3. Thread roots are resolved via `tgram.domain.threading.resolve_root()`.
4. An authoritative `MessageRepo.repair_virtual_topics(chat_id)` pass runs automatically after every fetch run that saved messages, recomputing clean reply chains.
5. FTS5 INSERT trigger on `messages` table auto-indexes new text.

**Data flow — search:**
1. Default hybrid retrieval: `FTSSearch.search()` queries FTS5 BM25 and `EmbeddingRepo.search_similar()` queries vector cosine similarity (filtered), merged via Reciprocal Rank Fusion (RRF).
2. Automatically falls back to FTS5-only when the query contains explicit operators (`"phrase"`, `term*`), when `--fts-only` is passed, or when Ollama is unreachable. Active mode is reported (`hybrid`, `fts (operators)`, etc.).
3. Conversation reconstruction: `FTSSearch.get_conversation()` reconstructs conversation context around hits (up to 12 thread messages: root, ancestor path, hit, direct replies, plus temporal window of ±2 neighbours in the same topic within 30 minutes).

**Data flow — AI Q&A:**
1. `AIService.ask_with_history()` embeds question with `search_query:` prefix via Ollama (falling back to FTS-only on embedder error).
2. Hybrid retrieval finds candidate hits; `_build_context()` reconstructs and groups deduplicated chronological conversation threads (`--- [topic] YYYY-MM-DD ---`) with `↳` marking replies.
3. Context budget is adapter-specific: `12,000` chars with `num_ctx=12288` for Ollama (`OllamaAdapter`); `24,000` chars for cloud models (`LiteLLMAdapter`).
4. Answers cite sources using `[msg:<id>]`.
5. Returns `(response, hits, context_index)` mapping message IDs to `(chat_id, message_id)` for citation resolution in Gradio web UI and CLI.

**SQLite schema (5 migration files):**
- `messages` — composite PK `(chat_id, id)`, stores full `raw_json` plus typed columns
- `channels` — per-channel state: `last_fetched_id`, `enabled`, `is_forum`
- `topics` — maps `(chat_id, topic_id)` → `title`
- `messages_fts` — FTS5 virtual table; keep-sync triggers on INSERT/UPDATE/DELETE
- `embeddings` — PK `(chat_id, message_id, chunk_idx)`, vector BLOB (768-dim float32 packed with `struct`), model TEXT; queried via `sqlite-vec`'s `vec_distance_cosine()`; WAL mode enabled

**Embedding details:**
- Model: `nomic-embed-text-v2-moe:latest` via Ollama (512-token context window)
- Texts are prepended with `search_document:` prefix before embedding; queries with `search_query:`
- Long messages are split into overlapping 400-char chunks (`_OVERLAP=50`) — each chunk is one row in `embeddings` with its own `chunk_idx`
- `search_similar()` groups by `(chat_id, message_id)` and returns `MIN(distance)` so each message appears once at its best-matching chunk
- Migration 005 (DROP+RENAME) is guarded in Python — skipped if `chunk_idx` already exists

**Topic & thread system:**
- *Native topics*: `reply_to_top_message_id` — set by Telegram for forum-type channels. General topic in forum channels has `reply_to_top_message_id = NULL`.
- *Virtual topics*: `virtual_topic_id` — reply-chain root resolved by `tgram.domain.threading.resolve_root()`. Forum top-level posts start their own thread (`virtual_topic_id = id`). Recomputed authoritatively by `repair_virtual_topics()`.
- Thread reconstruction: `python -m tgram thread <id>` or `make thread ID=<id>` inspects reconstructed conversation flow.

**Session management:** Telethon session stored at `data/sessions/tgram.session`. First run prompts for phone + SMS code interactively.

**Daemon:** `interfaces/daemon.py` runs a plain `asyncio` sleep loop. Polls enabled channels every `FETCH_INTERVAL_MINUTES`, refreshes dialog list every `REFRESH_DIALOGS_MINUTES`. Safe to run concurrently with `embed_all` (WAL mode).

**Web UI models** (first = default):
- Gemini 2.5 Flash Lite (`gemini/gemini-2.5-flash-lite`) — default, cloud
- Gemma 4 26B (`ollama/gemma4:26b` or `local`) — local Ollama
- Full LiteLLM provider support (Gemini, Claude, OpenAI, Ollama)
