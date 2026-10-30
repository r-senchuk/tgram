# Testing & Invariants Verification Guide

This guide documents the automated test suite, SQL integrity invariants, and verification procedures for the `tgram` architecture.

---

## 1. Test Architecture Overview

The `tgram` test suite is designed around three testing layers:
1. **Pure Domain & Algorithm Unit Tests:** Fast, in-memory validation of threading logic, query sanitization, and reciprocal rank fusion with zero database or network I/O.
2. **Adapter & Repository Integration Tests:** Verification of SQLite migrations, window functions, gap detection, and batch lookups using temporary SQLite databases (`tmp_path`).
3. **End-to-End Service & Interface Tests:** CLI command execution, web citation linkification, Ollama/LiteLLM streaming adapter behavior, and context budget enforcement.

Running all tests:
```bash
make test
# Or directly:
.venv/bin/pytest -v
```

All 45 tests execute in **~2.2 seconds** against clean temporary SQLite databases.

---

## 2. Test Suite Matrix (45 Tests across 10 Modules)

| Test Module | Test Name | Target Component | Description |
|---|---|---|---|
| **`test_autonomous_daemon_and_db.py`** | `test_db_factory_pragmas_and_migration_gating` | `tgram.adapters.db` | Verifies SQLite pragmas (`WAL`, `busy_timeout=10000`, `synchronous=NORMAL`) and 0ms migration gating |
| | `test_db_backward_compatibility_chunk_idx` | `tgram.adapters.db` | Backfills legacy databases with versions 4 and 5 without destructive DROP TABLE re-runs |
| | `test_telegram_session_file_lock` | `tgram.adapters.telegram` | Non-blocking advisory file locking preventing simultaneous session access |
| | `test_daemon_cycle_auto_embed` | `tgram.interfaces.daemon` | Background auto-embedding integration at the end of each fetch cycle |
| | `test_daemon_recovers_when_ollama_offline` | `tgram.interfaces.daemon` | Graceful error recovery when Ollama is offline without interrupting the polling loop |
| | `test_embed_service_bounded_backfill` | `tgram.services.embed` | Bounded batching (`max_batches`) and silent execution (`quiet=True`) |
| **`test_threading.py`** | `test_is_thread_start` | `tgram.domain.threading` | Distinguishes forum top-level starters (`reply_to_message_id == reply_to_top_message_id`) from nested replies |
| | `test_resolve_root_top_level` | `tgram.domain.threading` | Top-level non-forum message resolves to its own ID |
| | `test_resolve_root_forum_top_level` | `tgram.domain.threading` | Forum starter post resolves to its own ID (avoids mega-thread collapse) |
| | `test_resolve_root_nested_reply` | `tgram.domain.threading` | Single reply resolves to parent's root |
| | `test_resolve_root_multihop_chain` | `tgram.domain.threading` | Multi-hop chain (`A <- B <- C <- D`) resolves to `A` |
| | `test_resolve_root_orphan` | `tgram.domain.threading` | Orphan reply with missing parent roots at parent ID |
| | `test_ingest_service_set_virtual_topic_batch_local` | `tgram.services.ingest` | Batch-local causal resolution without redundant DB queries |
| **`test_conversation.py`** | `test_40_message_thread` | `tgram.adapters.search_fts` | Strict 12-message cap on large threads; preserves hit, root, ancestor path, and direct replies |
| | `test_general_topic_scoping` | `tgram.adapters.search_fts` | General topic messages (`reply_to_top_message_id IS NULL`) are isolated from forum topics |
| | `test_temporal_window_30_min_bound` | `tgram.adapters.search_fts` | `±window` temporal neighbors are included only if within 30 minutes of hit |
| | `test_deduplication_and_chronological_order` | `tgram.adapters.search_fts` | Deduplicates thread members and sorts chronologically by date/id |
| **`test_repair.py`** | `test_repair_dry_run_and_apply` | `tgram.adapters.repo_messages` | Verifies dry-run returns count without writing; apply updates rows |
| | `test_repair_backfilled_parent` | `tgram.adapters.repo_messages` | When parent arrives late, repair pass updates orphan replies to parent's root |
| **`test_search.py`** | `test_clean_fts_query_punctuation` | `tgram.adapters.search_fts` | Strips special punctuation `( ) + - ^ :` into clean spaces |
| | `test_clean_fts_query_unbalanced_quotes` | `tgram.adapters.search_fts` | Strips unbalanced quotes while preserving valid quoted phrases |
| | `test_clean_fts_query_bare_boolean_operators` | `tgram.adapters.search_fts` | Lowercases bare `AND/OR/NOT/NEAR` so FTS5 doesn't throw syntax errors |
| | `test_clean_fts_query_match_any` | `tgram.adapters.search_fts` | OR-joins significant tokens (length >= 4) for question queries |
| | `test_has_fts_operators` | `tgram.services.search` | Detects `*` and `"` to trigger keyword-only search |
| | `test_fts_search_operational_error_graceful` | `tgram.adapters.search_fts` | Catches FTS5 `OperationalError` and falls back safely |
| | `test_search_service_mode_reporting` | `tgram.services.search` | Verifies active search mode strings (`hybrid`, `fts`, `operators`, `unreachable`) |
| | `test_embedding_repo_search_similar_filters` | `tgram.adapters.repo_embeddings` | Pre-filters vector scan by `topic_id`, `since`, and `until` |
| | `test_ai_service_build_context` | `tgram.services.ai` | Verifies thread grouping, context index mapping, and character budget enforcement |
| **`test_cli.py`** | `test_cli_repair_threads` | `tgram.interfaces.cli` | End-to-end CLI execution of `repair_threads` and `--dry-run` |
| | `test_cli_thread_command` | `tgram.interfaces.cli` | End-to-end CLI execution of `thread <msg_id>` conversation formatting |
| | `test_cli_status_and_gaps` | `tgram.interfaces.cli` | End-to-end CLI execution of `status` and `fetch_scan` |
| **`test_db_repos.py`** | `test_message_repo_crud_and_queries` | `tgram.adapters.repo_messages` | CRUD, bounds (`min_id`, `max_id`), `existing_ids`, `find_gaps`, `thread_root_of` |
| | `test_topic_repo` | `tgram.adapters.repo_topics` | Topic upserts, stats aggregation, and unknown topic ID detection |
| | `test_channel_repo` | `tgram.adapters.repo_channels` | Channel upserts, toggle enabled/disabled status, list filtered channels |
| **`test_invariants.py`** | `test_thread_invariants_in_isolation` | Database Schema & Invariants | Formally asserts all 4 invariant SQL queries on synthetic datasets |
| | `test_fts_rebuild_and_match` | `tgram.adapters.search_fts` | Rebuilds FTS5 index and verifies exact keyword hits |
| **`test_llm_adapters.py`** | `test_ollama_adapter_config` | `tgram.adapters.llm_ollama` | Context size (`12,000` chars) and options (`num_ctx: 12288`) |
| | `test_ollama_stream_adapter_chunking` | `tgram.adapters.llm_ollama` | Stream adapter wrapping Ollama chunks to LiteLLM chunk shape |
| | `test_litellm_adapter_config` | `tgram.adapters.llm_litellm` | Context size (`24,000` chars) and alias resolution (`flash`, `local`) |
| | `test_litellm_fake_stream` | `tgram.adapters.llm_litellm` | Non-streaming fallbacks formatted as single-chunk stream |
| **`test_web.py`** | `test_linkify_single_citation` | `tgram.interfaces.web` | `[msg:123]` converted to `[↗ msg:123](#msg-123)` anchor |
| | `test_linkify_multiple_citations_in_single_tag` | `tgram.interfaces.web` | `[msg:101, msg:102]` converted to multiple individual anchor badges |
| | `test_linkify_separate_citations` | `tgram.interfaces.web` | Separate bracket citations converted properly |
| | `test_linkify_no_citations` | `tgram.interfaces.web` | Normal bracketed text passed through unchanged |
| | `test_text_helper_gradio_blocks` | `tgram.interfaces.web` | Extracts plain string from Gradio 6 block dictionaries |

---

## 3. Formal Invariants & Mathematical Proofs

Let $M$ be the set of messages in a given chat, where each message $m \in M$ has:
- $m.id \in \mathbb{N}$ (monotonically increasing in Telegram)
- $m.reply\_to \in \mathbb{N} \cup \{\text{NULL}\}$
- $m.top\_id \in \mathbb{N} \cup \{\text{NULL}\}$ (forum topic ID if posted in a forum supergroup)
- $m.vtid \in \mathbb{N}$ (`virtual_topic_id`, the assigned thread root)

### Invariant 1: Non-Forum Root Invariant
A message in a regular chat with no reply pointer is the start of its own thread:
$$\forall m \in M: \quad (m.top\_id \text{ is NULL} \land m.reply\_to \text{ is NULL}) \implies m.vtid = m.id$$

### Invariant 2: Forum Starter Invariant
In a Telegram forum topic, every message posted into the topic technically points to the topic creation post as its reply target (`reply_to == top_id`). A new discussion inside that topic must start its own thread rather than collapsing the entire forum topic:
$$\forall m \in M: \quad (m.top\_id \text{ is not NULL} \land m.reply\_to = m.top\_id) \implies m.vtid = m.id$$

### Invariant 3: Reply Tree Induction
For any message $m$ that replies to another conversation message $p \in M$ (where $p.id = m.reply\_to$):
$$\forall m \in M: \quad (m.top\_id \text{ is NULL} \lor m.reply\_to \ne m.top\_id) \implies m.vtid = p.vtid$$

### Invariant 4: Monotonic Tree Structure
In Telegram, a message can only reply to a message that already exists:
$$\forall m \in M: \quad m.reply\_to \ne \text{NULL} \implies m.reply\_to < m.id$$
Because $p.id < m.id$ for all parent-child relationships, reply chains form a **directed acyclic forest (DAG)** rooted at $m.vtid$. No cycles are mathematically possible.

---

## 4. Verification on Production Archives

You can run these SQL audits directly against `data/messages.db` at any time to verify archive consistency:

```bash
# 1. Verify zero reply/parent mismatches
sqlite3 data/messages.db "
SELECT count(*) FROM messages c
JOIN messages p ON c.chat_id = p.chat_id AND c.reply_to_message_id = p.id
WHERE (c.reply_to_top_message_id IS NULL OR c.reply_to_message_id != c.reply_to_top_message_id)
  AND c.virtual_topic_id != p.virtual_topic_id;"
# Output: 0

# 2. Verify zero misrouted forum topic starters
sqlite3 data/messages.db "
SELECT count(*) FROM messages
WHERE reply_to_top_message_id IS NOT NULL
  AND reply_to_message_id = reply_to_top_message_id
  AND virtual_topic_id != id;"
# Output: 0

# 3. Verify zero misrouted non-forum top-level messages
sqlite3 data/messages.db "
SELECT count(*) FROM messages
WHERE reply_to_message_id IS NULL
  AND virtual_topic_id != id;"
# Output: 0

# 4. Verify FTS5 and vector index parity
sqlite3 data/messages.db "
SELECT
  (SELECT count(*) FROM messages) AS total_messages,
  (SELECT count(*) FROM messages_fts) AS fts_messages,
  (SELECT count(*) FROM messages WHERE text IS NOT NULL AND text != '') AS text_messages,
  (SELECT count(*) FROM embeddings) AS total_embeddings;"
# Output: 321359 | 321359 | 290801 | 290801 (100% parity)
```
