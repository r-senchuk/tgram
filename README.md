# tgram — Telegram Archive + AI Q&A

Personal tool that archives Telegram channels/groups you belong to, lets you search the archive, and answers questions grounded in real chat history using a local or cloud LLM.

## Setup

```bash
git clone https://github.com/r-senchuk/tgram.git
cd tgram
python -m venv .venv && .venv/bin/pip install -r requirements.txt
cp env.template .env   # fill in API_ID, API_HASH from my.telegram.org
```

## Configuration (`.env`)

```env
API_ID=your_api_id
API_HASH=your_api_hash
CHAT_ID=-1001234567890      # default channel — used by `make` targets and --chat omission

# Daemon polling intervals
FETCH_INTERVAL_MINUTES=5
REFRESH_DIALOGS_MINUTES=60

# API keys for cloud models in the web UI (only the ones you want to use)
GEMINI_API_KEY=...
ANTHROPIC_API_KEY=...
OPENAI_API_KEY=...
```

## Makefile shortcuts

All common commands have `make` targets that use `CHAT_ID` from `.env` by default. Override with `CHAT=`:

```bash
make daemon                          # start background fetcher
make fetch-new                       # fetch new messages for default chat
make fetch-new CHAT=-1001593560584   # override chat

make search Q="карта резидента"
make ask Q="how do I open a company in Poland"

make embed                           # generate embeddings for default chat
make web
```

Full command reference below if you prefer `python -m tgram <cmd>` directly.

## Commands

### First-time authentication

```bash
python -m tgram list_chan
# Prompts for phone number + SMS code on first run.
# Session saved — subsequent runs authenticate silently.
```

### Fetching messages

```bash
# Fetch messages newer than the last stored one (incremental update)
python -m tgram fetch_new --chat -1001593560584

# Fetch full history backwards from the oldest stored message
python -m tgram fetch_old --chat -1001593560584

# Fetch full history and keep going until the channel beginning
python -m tgram fetch_old --chat -1001593560584 --loop

# Fetch a specific ID range (to fill a known gap)
python -m tgram fetch_gap 100000 101000 --chat -1001593560584

# Show storage stats and gap count
python -m tgram status --chat -1001593560584

# Show all detected gaps
python -m tgram fetch_scan --chat -1001593560584
```

### Multi-channel management

```bash
# Discover all your Telegram channels/groups
python -m tgram channels refresh

# List all known channels (✓ = enabled for fetch_all)
python -m tgram channels list

# Enable specific channels for automatic fetching
python -m tgram channels enable -- -1001593560584 -1001919096489

# Disable a channel
python -m tgram channels disable -- -1001593560584

# Fetch new messages for all enabled channels at once
python -m tgram fetch_all
```

### Daemon (background auto-fetch)

```bash
# Keeps all enabled channels up to date automatically
# Fetches every FETCH_INTERVAL_MINUTES (default: 5)
# Ctrl+C to stop cleanly
python -m tgram daemon
```

### Topics (forum channels)

```bash
# Fetch topic names from Telegram and store them
python -m tgram sync_topics --chat -1001593560584

# List all topics with message counts
python -m tgram list_topics --chat -1001593560584
```

### Search

```bash
# Full-text search across all messages (run once first to build index)
python -m tgram rebuild_fts

# Basic search
python -m tgram search "карта резидента"

# Filter by channel or topic
python -m tgram search "JDG" --chat -1001593560584
python -m tgram search "квартира" --topic 10776

# Filter by date
python -m tgram search "податки" --since 2026-01-01

# Show surrounding conversation (N messages before/after each hit)
python -m tgram search "карта резидента" --context 3

# Prefix and phrase search (FTS5 syntax)
python -m tgram search "легаліз*"
python -m tgram search '"карта побиту"'
```

### Semantic embeddings

Requires Ollama with `nomic-embed-text-v2-moe:latest` pulled. Enables hybrid search (keywords + semantic meaning) for the `ask` command and web UI.

Long messages are automatically split into overlapping 400-char chunks (safe for the model's 512-token context window). The process is idempotent — safe to interrupt and resume.

```bash
# Generate embeddings for all stored messages
python -m tgram embed_all --chat -1001593560584

# Run concurrently with daemon — WAL mode prevents locking conflicts
make embed &
make daemon
```

After embeddings are built, `ask` and `web` automatically use hybrid retrieval (FTS5 BM25 + vector cosine via RRF) when Qwen is selected.

### AI Q&A

Requires Ollama with `qwen3.6:35b-a3b-q4_k_m` pulled for the CLI `ask` command.

```bash
# Ask a question — answered from real chat messages
python -m tgram ask "Що таке карта сталого побуту?"

# Focus on a specific topic
python -m tgram ask "Як відкрити JDG?" --topic 3302

# Filter by channel
python -m tgram ask "Where can I rent an apartment?" --chat -1001593560584

# Suppress chain-of-thought for faster answers
python -m tgram ask "Яка різниця між статусом та резидентом?" --no-think

# Print full answer at once (no streaming)
python -m tgram ask "summary of legalization discussions" --no-stream
```

Answers include `[msg:XXXXXX]` citations. Verify any citation:
```bash
sqlite3 data/messages.db "SELECT date, username, text FROM messages WHERE id = XXXXXX;"
```

### Web UI (Gradio)

Chat interface with model selector, topic filter, and streaming responses. Opens at `http://localhost:7860`.

Available models: Gemma 3 27B (default), Gemini 2.5 Flash Lite, Gemini 2.5 Flash, Qwen 35B (local), Claude Sonnet, GPT-4o. Cloud models require the corresponding `*_API_KEY` in `.env`.

```bash
python -m tgram web --chat -1001593560584
```

## Roadmap

| Phase | Status |
|---|---|
| 1 — Bootstrap (Telethon, schema, ingest) | ✅ Done |
| 2 — Multi-channel + Daemon | ✅ Done |
| 3 — FTS5 Search | ✅ Done |
| 4a — AI Q&A via Ollama + LiteLLM | ✅ Done |
| 4b — Gradio web UI + multi-turn chat | ✅ Done |
| 4c — Semantic embeddings + hybrid retrieval | ✅ Done |

## License

MIT
