# Implementation Plans — tgram

This directory contains phased implementation plans for `tgram`.

## Current status

| # | Phase | Status | Notes |
|---|---|---|---|
| 1 | Bootstrap (Telethon, schema, single-channel ingest) | ✅ Done | |
| 2 | Multi-channel + Daemon | ✅ Done | |
| 3 | FTS5 Search | ✅ Done | `search`, `rebuild_fts` commands working |
| 4 | AI Q&A (embeddings + LiteLLM + Gradio) | ⬜ Next | See PHASE_4_ai_qa.md |

## Stack (locked in)

| Layer | Choice |
|---|---|
| Telegram client | Telethon |
| Storage | SQLite + FTS5 + sqlite-vec (Phase 4) |
| LLM router | LiteLLM |
| Local LLM | Ollama `qwen3.6:35b-a3b-q4_k_m` (already installed) |
| Embeddings | Ollama `nomic-embed-text-v2-moe:latest` (already installed) |
| Web UI | Gradio (Phase 4) |

## Phase files

Each file is self-contained — any AI model can pick it up and implement the phase without reading the others.

- [PHASE_1_bootstrap.md](PHASE_1_bootstrap.md) ✅
- [PHASE_2_multi_channel_daemon.md](PHASE_2_multi_channel_daemon.md) ✅
- [PHASE_3_search.md](PHASE_3_search.md) ✅
- [PHASE_4_ai_qa.md](PHASE_4_ai_qa.md) ⬜ — next
