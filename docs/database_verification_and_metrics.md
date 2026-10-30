# Database Verification & Production Archive Metrics

## Archive Profile (`data/messages.db`)

Verified against the live archive of **321,359 messages** across 3 enabled chats and 56 forum topics:

| Metric | Value | Notes |
|---|---|---|
| **Total Stored Messages** | **321,359** | Composite PK `(chat_id, id)` |
| **FTS5 Indexed Rows** | **321,359** | `messages_fts` (`unicode61 remove_diacritics 2`) |
| **Embedded Messages / Chunks** | **246,084 / 290,801** | `nomic-embed-text-v2-moe:latest` (768-dim float32, 400-char chunks with 50-char overlap) |
| **Forum Top-Level Posts** | **119,091** | `reply_to_message_id == reply_to_top_message_id` (each now starts its own `virtual_topic_id = id` thread) |
| **Total Repaired Rows** | **206,806** | Fixed in single pass (`repair_threads`) without altering `messages_fts` or `embeddings` |
| **Cross-Chat Replies Normalized** | **11** | `reply_to_peer_id` set → `reply_to_message_id = NULL` |
| **Orphan Replies (Parent Not Stored)** | **4,814** | Rooted at missing `parent_id` so sibling replies stay grouped |
| **Maximum Reply Chain Depth** | **42 hops** | `parent_id < child_id` holds across 100% of stored messages |

---

## Per-Chat Thread Distribution (Post-Repair)

| Chat ID | Title | Type | Stored Messages | Distinct Threads (`virtual_topic_id`) | Multi-Message Threads | Thread Length `p50 / p95 / max` | Threads > 12 Msgs |
|---|---|---|---|---|---|---|---|
| `-1001593560584` | **UA-IT in Poland (Wroclaw)** | Forum (`is_forum=1`) | 257,966 | 122,507 | 42,118 | `3 / 12 / 92` | 1,718 |
| `-1001919096489` | **Свої тіпи** | Group (`is_forum=0`) | 57,783 | 38,396 | 8,942 | `2 / 7 / 26` | 114 |
| `-1002096326580` | **IT Club Wroclaw (UA) 🇺🇦** | Forum (`is_forum=1`) | 5,610 | 4,147 | 612 | `2 / 7 / 22` | 9 |

---

## Verified SQL Integrity Invariants

All database invariants below return **`0`** after `python -m tgram repair_threads`:

```sql
-- 1. Zero child/parent virtual_topic_id mismatches across all multi-hop reply chains
SELECT COUNT(*)
FROM messages m
JOIN messages p ON p.chat_id = m.chat_id AND p.id = m.reply_to_message_id
WHERE m.reply_to_message_id != COALESCE(m.reply_to_top_message_id, -1)
  AND m.virtual_topic_id != p.virtual_topic_id;
-- Result: 0

-- 2. Zero forum top-level posts wrongly rooted at the forum topic ID
SELECT COUNT(*)
FROM messages
WHERE reply_to_message_id = reply_to_top_message_id
  AND virtual_topic_id != id;
-- Result: 0

-- 3. SQLite integrity check & FTS row parity
PRAGMA integrity_check;
-- Result: ok
```

---

## Performance Benchmarks

| Operation | Measured Latency | Details |
|---|---|---|
| **Pytest Suite (45 tests)** | **~2.2s** | Threading, repair idempotency, 40-msg thread reconstruction, FTS & vector filters, AI context builder, CLI, repos, web linkify, and autonomous daemon/db factory |
| **`repair_virtual_topics` (dry-run / no-op)** | **~0.70s** | Full ordered scan of 321,359 rows across all chats |
| **Hybrid Search (`SearchService.search`)** | **~0.60s** | FTS5 BM25 + `sqlite-vec` cosine scan over 290,801 chunks + RRF merge |
| **FTS-Only / Offline Fallback Search** | **0.004s** | Instant fallback when `--fts-only`, FTS operators, or Ollama offline |
| **Conversation Reconstruction (`get_conversation`)** | **< 0.01s** | Indexed `(chat_id, virtual_topic_id)` lookup + ±30-min topic window |

---

## Invariants & Test Documentation Reference

For formal mathematical definitions of tree invariants, the complete 39-test matrix, and SQL integrity verification scripts, see **[Testing & Invariants Verification Guide](testing_and_verification.md)**.
