# tgram — Telegram Archive, Conversation Search & Grounded AI Q&A

Personal local-first tool that archives Telegram channels, supergroups, and forum groups you belong to into a single SQLite database (`data/messages.db`), reconstructs multi-message reply chains and conversation threads, provides hybrid semantic + keyword search, and answers questions grounded in real chat discussions with clickable `[msg:ID]` citations.

---

## Key Capabilities

- **Causal, Gap-Free Telegram Ingest:** Fetches messages via Telethon (`reverse=True` oldest-first on `fetch_new`), preserves full `raw_json` alongside normalized columns, and resolves multi-hop reply chains (`virtual_topic_id`) automatically after every fetch (~0.5s pass).
- **Reproducible Conversation Flows:** Reconstructs human conversations around any hit by combining the explicit reply chain (thread root + ancestor path + hit + direct replies) with a time-bounded temporal window (`±2` adjacent messages in the same topic within 30 minutes).
- **Hybrid Semantic + Keyword Search:** Combines SQLite FTS5 (`unicode61` BM25) and `sqlite-vec` cosine similarity (`nomic-embed-text-v2-moe:latest`, 768-dim) via Reciprocal Rank Fusion (`k=60`). Automatically falls back to FTS-only when phrase/prefix operators (`"phrase"`, `term*`) are used, when `--fts-only` is passed, or when Ollama is offline.
- **Thread-Grounded AI Q&A (CLI & Gradio Web UI):** Feeds deduplicated chronological conversation threads (`--- [topic] YYYY-MM-DD ---` with `↳` reply indicators) to local Ollama (`gemma4:26b` with `num_ctx=12288`, 12k char budget) or cloud LLMs via LiteLLM (`gemini-2.5-flash-lite`, Claude, GPT-4o, 24k char budget).

---

## Architecture Overview

Imports flow strictly downward across layers:

```text
tgram/
├── interfaces/     cli.py, daemon.py, web.py        — CLI commands, polling daemon, Gradio UI
├── services/       ingest.py, search.py,            — Use-case orchestration (no direct SQL/network I/O)
│                   ai.py, embed.py
├── adapters/       telegram.py, repo_messages.py,   — Telethon, SQLite, FTS5, sqlite-vec,
│                   repo_channels.py, repo_topics.py,  Ollama & LiteLLM adapters
│                   repo_embeddings.py, search_fts.py,
│                   llm_ollama.py, llm_litellm.py
├── domain/         message.py, channel.py,          — Frozen dataclasses & pure thread resolution
│                   topic.py, threading.py
└── migrations/     001_*.sql … 005_*.sql            — SQLite schema, FTS5 triggers, chunked vectors
```

See [docs/architecture_and_data_flow.md](docs/architecture_and_data_flow.md) for the complete data flow and schema reference.

---

## Setup

```bash
git clone https://github.com/r-senchuk/tgram.git
cd tgram
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt pytest
cp env.template .env   # fill in API_ID, API_HASH from https://my.telegram.org
```

## Configuration (`.env`)

```env
API_ID=your_api_id
API_HASH=your_api_hash
CHAT_ID=-1001234567890      # default channel — used by `make` targets and --chat omission

# Daemon polling intervals
FETCH_INTERVAL_MINUTES=5
REFRESH_DIALOGS_MINUTES=60

# API keys for cloud models in the web UI / LiteLLM (only the ones you use)
GEMINI_API_KEY=...
ANTHROPIC_API_KEY=...
OPENAI_API_KEY=...
```

---

## Makefile Shortcuts

Common workflows have `make` targets that use `CHAT_ID` from `.env` for single-chat operations and search across **all** chats when `CHAT=` is omitted:

```bash
make daemon                          # start background fetcher
make fetch-new                       # fetch new messages for default chat (oldest-first)
make fetch-new CHAT=-1001593560584   # override chat

make repair-threads                  # recompute virtual_topic_id reply chains
make thread ID=150235                # reconstruct conversation around message ID

make search Q="карта резидента"      # hybrid semantic + FTS5 search
make ask Q="Як відкрити JDG?"        # AI Q&A grounded in conversation threads

make embed                           # generate embeddings for unembedded messages
make web                             # launch Gradio web UI on http://localhost:7860
```

---

## Command Reference

### 1. First-Time Authentication

```bash
python -m tgram list_chan
# Prompts for phone number + SMS code on first run.
# Session saved to data/sessions/tgram.session — subsequent runs authenticate silently.
```

### 2. Fetching Messages

Messages are fetched causally (`reverse=True` oldest-first on `fetch_new`) so interrupted runs never leave gaps below `max_id`. Reply chains are resolved with `tgram.domain.threading.resolve_root`, and an authoritative `repair_virtual_topics` pass runs automatically after every fetch that saves rows.

```bash
# Fetch messages newer than the highest stored ID (oldest-first)
python -m tgram fetch_new --chat -1001593560584

# Fetch one batch of history older than the lowest stored ID
python -m tgram fetch_old --chat -1001593560584

# Keep fetching older history until the channel beginning is reached
python -m tgram fetch_old --chat -1001593560584 --loop

# Fetch a specific ID range (to fill a gap reported by fetch_scan)
python -m tgram fetch_gap 100000 101000 --chat -1001593560584

# Show storage stats, ID bounds, topic counts, and gap count
python -m tgram status --chat -1001593560584

# List all detected message ID gaps
python -m tgram fetch_scan --chat -1001593560584
```

### 3. Threads & Conversation Reconstruction

Forum top-level posts (`reply_to_message_id == reply_to_top_message_id`) start their own conversation thread (`virtual_topic_id = id`), while nested replies inherit the root of their reply chain.

```bash
# Recompute virtual_topic_id reply chains across all chats (or a specific --chat)
python -m tgram repair_threads
python -m tgram repair_threads --chat -1001593560584 --dry-run
make repair-threads

# Reconstruct and display the conversation around a specific message ID
# Includes: thread root, ancestor chain, the target message (>>>), direct replies,
# and ±window temporal neighbours in the same topic within 30 minutes
python -m tgram thread 150235
python -m tgram thread 150235 --chat -1001593560584 --window 2
make thread ID=150235
```

### 4. Multi-Channel Management & Background Daemon

```bash
# Sync all your Telegram dialogs into the channels table (new channels default to disabled)
python -m tgram channels refresh

# List all known channels (✓ = enabled for fetch_all / daemon)
python -m tgram channels list

# Enable or disable channels for automatic fetching
python -m tgram channels enable -- -1001593560584 -1001919096489
python -m tgram channels disable -- -1001593560584

# Fetch new messages + sync topic names across all enabled channels
python -m tgram fetch_all

# Run continuous background daemon (polls every FETCH_INTERVAL_MINUTES)
python -m tgram daemon
```

### 5. Forum Topics

```bash
# Fetch human-readable topic titles from Telegram for unknown topic IDs
python -m tgram sync_topics --chat -1001593560584

# List all forum topics sorted by message count and last activity
python -m tgram list_topics --chat -1001593560584
```

### 6. Hybrid Semantic & Full-Text Search

`search` defaults to **hybrid mode** (FTS5 BM25 + `sqlite-vec` cosine similarity merged via Reciprocal Rank Fusion) and prints the active mode (`mode: hybrid`, `mode: fts`, `mode: fts (operators)`, or `mode: fts (ollama unreachable)`) to `stderr`.

```bash
# Hybrid search (default)
python -m tgram search "карта резидента"

# Reconstruct conversation threads around each search hit
python -m tgram search "карта резидента" --context 2

# Keyword-only FTS5 search (skips Ollama embedding)
python -m tgram search "карта резидента" --fts-only

# Filter by channel, forum topic, or date range (applies to both FTS and vector search)
python -m tgram search "податки" --chat -1001593560584 --topic 3302 --since 2025-01-01

# Phrase and prefix queries (automatically switch to `mode: fts (operators)`)
python -m tgram search "легаліз*"
python -m tgram search '"карта побиту"'

# Rebuild FTS5 index from scratch if needed
python -m tgram rebuild_fts
```

### 7. Semantic Embeddings

Requires Ollama running locally with `nomic-embed-text-v2-moe:latest`. Long messages are split into overlapping 400-character chunks (`_OVERLAP=50`) with the `search_document: ` prefix. Safe to interrupt and resume or run alongside `make daemon`.

```bash
# Generate embeddings for all unembedded messages (all chats or specific --chat)
python -m tgram embed_all
python -m tgram embed_all --chat -1001593560584 --batch 100
make embed
```

### 8. AI Q&A (`ask`) & Gradio Web UI (`web`)

Retrieves relevant messages via hybrid search, expands top hits into deduplicated chronological conversation threads (`--- [topic] YYYY-MM-DD ---`), and streams grounded answers with `[msg:<id>]` citations.

- **Local Ollama (`gemma4:26b`)**: `12,000` char context budget with `num_ctx=12288`.
- **Cloud Models (`LiteLLMAdapter`)**: `24,000` char context budget.

```bash
# Ask a question from the CLI
python -m tgram ask "Що таке карта сталого побуту?"
python -m tgram ask "Як відкрити JDG?" --topic 3302 --chat -1001593560584
python -m tgram ask "Яка різниця між статусом та резидентом?" --no-think

# Launch the Gradio Web UI (http://localhost:7860)
# Clicking any [↗ msg:N] badge opens the full reconstructed conversation thread
python -m tgram web
python -m tgram web --chat -1001593560584 --port 7860
```

### 9. Running Tests

```bash
.venv/bin/python -m pytest -v
```

---

## Documentation (`docs/` & `plans/`)

Detailed architecture, benchmarks, and strategic roadmaps are maintained in the [`docs/`](docs/) and [`plans/`](plans/) directories:

### Architecture, Metrics & Strategy (`docs/`)
- **[Architecture, Threading & Hybrid Retrieval Data Flow](docs/architecture_and_data_flow.md)** — Layered design, SQLite schema, Telethon forum vs. reply semantics, `resolve_root` & `repair_virtual_topics`, `get_conversation` priority algorithm, and hybrid RRF search.
- **[Database Verification & Production Archive Metrics](docs/database_verification_and_metrics.md)** — Live benchmarks on 321k+ messages and 290k+ embeddings, per-chat thread distributions, SQL integrity invariants, and query latency measurements.
- **[Development Strategy, Enhancements & Stability Roadmap](docs/development_strategy_and_roadmap.md)** — Next phases (auto-embedding daemon, thread-contextual embeddings, cross-encoder reranking, FastMCP server), library replacement trade-offs (`sqlite-vec` vs. LanceDB, `flashrank`, `semchunk`), and SQLite/Telethon hardening.

### Historical & Phase Design Docs (`docs/` & `plans/`)
- [Phase 1: Bootstrap](plans/PHASE_1_bootstrap.md) · [Phase 2: Multi-Channel Daemon](plans/PHASE_2_multi_channel_daemon.md) · [Phase 3: FTS5 Search](plans/PHASE_3_search.md) · [Phase 4: AI Q&A](plans/PHASE_4_ai_qa.md)
- Legacy notes: [Telegram Pipeline Overview](docs/telegram_pipeline_overview.md) · [Topic Functionality](docs/topic_functionality_implementation.md) · [Storage Requirements](docs/storage_requirements_and_implementation.md)

---

## Roadmap

| Phase | Description | Status |
|---|---|---|
| **1 — Bootstrap** | Telethon adapter, SQLite schema, incremental & backfill ingest | ✅ Done |
| **2 — Multi-Channel + Daemon** | Channel management (`channels`), topic sync, background polling daemon | ✅ Done |
| **3 — FTS5 Search** | `messages_fts` (`unicode61`), sync triggers, BM25 ranking | ✅ Done |
| **4a — AI Q&A** | Grounded RAG with `[msg:ID]` citations via Ollama & LiteLLM | ✅ Done |
| **4b — Gradio Web UI** | Multi-turn chat, dark/light glass theme, clickable citation context | ✅ Done |
| **4c — Semantic Embeddings** | Chunked 768-dim vectors (`sqlite-vec`) + Reciprocal Rank Fusion | ✅ Done |
| **5 — Causal Threading & Conversations** | Oldest-first `fetch_new`, 206.8k thread repair, `get_conversation`, filtered hybrid search | ✅ Done |
| **6 — Autonomous Daemon & Hardening** | Incremental auto-embed in daemon, SQLite pragma factory, session file lock | 📋 Planned ([Strategy](docs/development_strategy_and_roadmap.md)) |
| **7 — Thread Embeddings & Reranking** | Thread-contextual embeddings, `flashrank` cross-encoder, multi-turn query rewriting | 📋 Planned ([Strategy](docs/development_strategy_and_roadmap.md)) |
| **8 — MCP Server & Knowledge Distillation** | `FastMCP` server for AI assistants + automated per-topic FAQ distillation | 📋 Planned ([Strategy](docs/development_strategy_and_roadmap.md)) |

## License

MIT
