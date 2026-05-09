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
              topic.py
migrations/   001_*.sql … 005_*.sql      — applied in sorted order on every startup
```

**Data flow — ingest:**
1. `TelegramClientAdapter.iter_history()` yields `Message` domain objects from Telethon
2. `IngestService._stream_and_save()` buffers 500 messages, calls `MessageRepo.save_many()` per batch
3. `IngestService._set_virtual_topic()` walks `reply_to_message_id` chain via `MessageRepo.reply_root()` and stamps `virtual_topic_id` on each message before saving
4. FTS5 INSERT trigger on `messages` table auto-indexes new text

**Data flow — search:**
1. `FTSSearch.search()` runs FTS5 MATCH query, joins `messages` + `topics`, returns `SearchHit` list with BM25 snippet
2. When `embedding_repo` is set and `query_vector` is passed, also runs cosine similarity via `EmbeddingRepo.search_similar()` and merges results with Reciprocal Rank Fusion
3. `FTSSearch.get_context()` fetches surrounding messages in the same topic thread

**Data flow — AI Q&A:**
1. `AIService.ask_with_history()` embeds the question with `search_query:` prefix via `OllamaAdapter.embed()` (when Ollama is the LLM)
2. Hybrid retrieval: FTS5 BM25 + vector cosine, merged via RRF
3. Top-K messages formatted as `<archive>` context, sent to LLM with conversation history
4. Streams response back to CLI or Gradio UI

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

**Topic system:**
- *Native topics*: `reply_to_top_message_id` — set by Telegram for forum-type channels
- *Virtual topics*: `virtual_topic_id` — reply-chain root, computed locally by walking `reply_to_message_id`

**Session management:** Telethon session stored at `data/sessions/tgram.session`. First run prompts for phone + SMS code interactively.

**Daemon:** `interfaces/daemon.py` runs a plain `asyncio` sleep loop. Polls enabled channels every `FETCH_INTERVAL_MINUTES`, refreshes dialog list every `REFRESH_DIALOGS_MINUTES`. Safe to run concurrently with `embed_all` (WAL mode).

**Web UI models** (first = default):
- Gemma 3 27B (`gemini/gemma-3-27b-it`) — default, think off
- Gemini 2.5 Flash Lite (`gemini/gemini-2.5-flash-lite`)
- Gemini 2.5 Flash
- Qwen 35B local (`ollama/qwen3.6:35b-a3b-q4_k_m`) — activates hybrid search
- Claude Sonnet, GPT-4o

## Key known issues / not yet implemented

- `fetch_scan` shows real gaps but `fetch_gap` must be called manually to fill them — no auto-fill
- Embeddings are not generated automatically on ingest — run `make embed` manually after large fetches
- Hybrid search only activates when Qwen (Ollama) is the LLM; cloud models use FTS-only retrieval
