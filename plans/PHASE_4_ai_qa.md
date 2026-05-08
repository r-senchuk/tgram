# Phase 4 — AI Q&A (Embeddings + Hybrid Retrieval + Multi-LLM + Gradio)

## Read first

This phase assumes Phases 1–3 have landed. The archive is multi-channel, the daemon polls in the background, and FTS5 search returns ranked results in <100ms. Read [README.md](README.md) for the full tool stack.

## Goal

The user can ask a natural-language question and get an answer **grounded in real chat messages**, with citations. Backed by hybrid retrieval (FTS5 + vector) and routed to any LLM via LiteLLM. A Gradio chat UI gives a streaming chat experience in the browser.

```bash
python -m tgram ask "What did people say about the release last week?"
python -m tgram ask "Какие были вопросы про деплой?" --model claude
python -m tgram web        # opens browser to a chat UI
```

## Locked-in choices for this phase

| Concern | Choice |
|---|---|
| LLM router | LiteLLM |
| Default LLM | Ollama `qwen3.6:35b-a3b-q4_k_m` (local; user already has it) |
| Other LLMs | Claude (`anthropic/claude-sonnet-4-7`), OpenAI (`openai/gpt-4o`), Gemini (`gemini/gemini-2.0-pro`), Kimi via OpenRouter (`openrouter/moonshotai/kimi-k2`) |
| Embeddings | Ollama `nomic-embed-text-v2-moe:latest` (already installed) — 768-dim, multilingual MoE |
| Vector store | sqlite-vec |
| Retrieval | FTS5 + vector, fused via Reciprocal Rank Fusion (k=60) |
| UI | Gradio `gr.ChatInterface` with streaming |

## New dependencies

Append to `requirements.txt`:
```text
sqlite-vec>=0.1.6
litellm>=1.50.0
gradio>=5.0.0
ollama>=0.4.0
```

## Steps

### 1. Vector schema migration

Create `tgram/migrations/005_vectors.sql`:

```sql
-- sqlite-vec virtual table for 768-dim float vectors.
-- nomic-embed-text-v2-moe outputs 768 dimensions.
CREATE VIRTUAL TABLE IF NOT EXISTS message_vectors USING vec0(
    embedding float[768]
);

-- Mapping table from messages.rowid → message_vectors.rowid.
-- (vec0 doesn't support composite-PK foreign keys, so we map.)
CREATE TABLE IF NOT EXISTS message_vector_map (
    message_rowid INTEGER PRIMARY KEY REFERENCES messages(rowid),
    vec_rowid     INTEGER NOT NULL UNIQUE,
    model         TEXT NOT NULL,
    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Track which messages still need embedding.
CREATE TABLE IF NOT EXISTS embedding_queue (
    message_rowid INTEGER PRIMARY KEY,
    enqueued_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Trigger: queue every newly-inserted text message for embedding.
CREATE TRIGGER IF NOT EXISTS messages_ai_embed AFTER INSERT ON messages
WHEN new.text IS NOT NULL AND length(new.text) >= 5
BEGIN
    INSERT OR IGNORE INTO embedding_queue (message_rowid) VALUES (new.rowid);
END;

INSERT OR IGNORE INTO schema_version (version) VALUES (5);
```

### 2. Load sqlite-vec extension

In `tgram/adapters/repo_messages.py`, modify `_conn()` (or a new `_vec_conn()`) to load the extension:

```python
import sqlite_vec

@contextmanager
def _conn(self):
    conn = sqlite3.connect(self.db_path)
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()
```

### 3. `tgram/adapters/embeddings.py`

```python
import asyncio
import logging
from typing import Iterable

import ollama

logger = logging.getLogger(__name__)

EMBED_MODEL = "nomic-embed-text-v2-moe:latest"
EMBED_DIM = 768


class OllamaEmbedder:
    def __init__(self, model: str = EMBED_MODEL, host: str | None = None):
        self.model = model
        self._client = ollama.AsyncClient(host=host) if host else ollama.AsyncClient()

    async def embed(self, text: str) -> list[float]:
        resp = await self._client.embed(model=self.model, input=text)
        return resp["embeddings"][0]

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        # Ollama embed accepts a list directly.
        resp = await self._client.embed(model=self.model, input=texts)
        return resp["embeddings"]
```

### 4. `tgram/adapters/vector_store.py`

```python
import sqlite3
import struct
from contextlib import contextmanager
from pathlib import Path

import sqlite_vec


class VectorStore:
    def __init__(self, db_path: Path, model_name: str, dim: int = 768):
        self.db_path = Path(db_path)
        self.model_name = model_name
        self.dim = dim

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def _pack(vec: list[float]) -> bytes:
        return struct.pack(f"{len(vec)}f", *vec)

    def upsert(self, message_rowid: int, vector: list[float]) -> None:
        if len(vector) != self.dim:
            raise ValueError(f"Expected dim {self.dim}, got {len(vector)}")
        with self._conn() as c:
            cur = c.execute(
                "INSERT INTO message_vectors (embedding) VALUES (?)",
                (self._pack(vector),),
            )
            vec_rowid = cur.lastrowid
            c.execute(
                """INSERT OR REPLACE INTO message_vector_map
                   (message_rowid, vec_rowid, model) VALUES (?, ?, ?)""",
                (message_rowid, vec_rowid, self.model_name),
            )

    def search(self, query_vector: list[float], k: int = 50,
               chat_id: int | None = None) -> list[tuple[int, float]]:
        """Returns [(message_rowid, distance), …] sorted by ascending distance."""
        sql = """
            SELECT m.rowid AS message_rowid, mv.distance AS dist
            FROM message_vectors mv
            JOIN message_vector_map map ON map.vec_rowid = mv.rowid
            JOIN messages m ON m.rowid = map.message_rowid
            WHERE mv.embedding MATCH ? AND k = ?
        """
        params: list = [self._pack(query_vector), k]
        if chat_id is not None:
            sql += " AND m.chat_id = ?"
            params.append(chat_id)
        sql += " ORDER BY dist"
        with self._conn() as c:
            return [(r[0], r[1]) for r in c.execute(sql, params).fetchall()]
```

### 5. `tgram/services/embed_worker.py`

Background task that drains `embedding_queue` and writes vectors. Runs on the daemon's APScheduler too.

```python
import asyncio
import logging
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from tgram.adapters.embeddings import OllamaEmbedder, EMBED_MODEL
from tgram.adapters.vector_store import VectorStore

logger = logging.getLogger(__name__)


class EmbedWorker:
    BATCH = 32

    def __init__(self, db_path: Path, embedder: OllamaEmbedder, store: VectorStore):
        self.db_path = Path(db_path)
        self.embedder = embedder
        self.store = store

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self.db_path)
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    async def drain(self, max_batches: int = 10) -> int:
        """Process pending queue. Returns count embedded."""
        embedded_total = 0
        for _ in range(max_batches):
            with self._conn() as c:
                rows = c.execute(
                    """SELECT q.message_rowid, m.text
                       FROM embedding_queue q
                       JOIN messages m ON m.rowid = q.message_rowid
                       LIMIT ?""", (self.BATCH,),
                ).fetchall()
            if not rows:
                return embedded_total

            rowids = [r[0] for r in rows]
            texts = [r[1] for r in rows]

            try:
                vectors = await self.embedder.embed_batch(texts)
            except Exception as e:
                logger.exception(f"Embedding batch failed: {e}")
                return embedded_total

            for rid, vec in zip(rowids, vectors):
                try:
                    self.store.upsert(rid, vec)
                except Exception as e:
                    logger.exception(f"Vector store upsert failed for rowid={rid}: {e}")
                    continue

            with self._conn() as c:
                c.executemany(
                    "DELETE FROM embedding_queue WHERE message_rowid = ?",
                    [(rid,) for rid in rowids],
                )
            embedded_total += len(rowids)
            await asyncio.sleep(0)  # yield
        return embedded_total
```

### 6. Hybrid retrieval (RRF)

Replace `tgram/services/retrieval.py` content from Phase 3 with:

```python
import logging
from dataclasses import dataclass

from tgram.adapters.embeddings import OllamaEmbedder
from tgram.adapters.search_fts import FTSSearch, SearchHit
from tgram.adapters.vector_store import VectorStore
from tgram.adapters.repo_messages import MessageRepo

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RetrievalResult:
    hits: list[SearchHit]
    method: str


class Retriever:
    """Hybrid retrieval: FTS5 + vector, fused via Reciprocal Rank Fusion (k=60)."""

    K_RRF = 60

    def __init__(self, fts: FTSSearch, vec: VectorStore,
                 embedder: OllamaEmbedder, repo: MessageRepo):
        self.fts = fts
        self.vec = vec
        self.embedder = embedder
        self.repo = repo

    async def retrieve(self, query: str, *, chat_id: int | None = None,
                       limit: int = 30) -> RetrievalResult:
        # 1. FTS5 retrieval
        fts_hits = self.fts.search(query, chat_id=chat_id, limit=limit * 2)
        # 2. Vector retrieval
        try:
            qvec = await self.embedder.embed(query)
            vec_results = self.vec.search(qvec, k=limit * 2, chat_id=chat_id)
        except Exception as e:
            logger.warning(f"Vector retrieval failed, falling back to FTS only: {e}")
            return RetrievalResult(hits=fts_hits[:limit], method="fts")

        # 3. RRF fusion
        # Map: message rowid → SearchHit (build from fts and lookup repo for vec-only)
        # We approximate "rowid" via (chat_id, id) → rowid lookup.
        fts_rank = {(h.message.chat_id, h.message.id): i + 1
                    for i, h in enumerate(fts_hits)}

        # Resolve vec_results (which are message_rowid) back to (chat_id, id)
        vec_keys = self._rowids_to_keys([r[0] for r in vec_results])
        vec_rank = {k: i + 1 for i, k in enumerate(vec_keys)}

        all_keys = set(fts_rank) | set(vec_rank)
        scored: list[tuple[tuple[int, int], float]] = []
        for k in all_keys:
            r1 = fts_rank.get(k, len(fts_hits) + 1)
            r2 = vec_rank.get(k, len(vec_results) + 1)
            score = 1.0 / (self.K_RRF + r1) + 1.0 / (self.K_RRF + r2)
            scored.append((k, score))
        scored.sort(key=lambda x: x[1], reverse=True)

        # Materialize top-`limit` as SearchHits using FTS hits where present,
        # else fetch from repo.
        fts_by_key = {(h.message.chat_id, h.message.id): h for h in fts_hits}
        out: list[SearchHit] = []
        for key, _score in scored[:limit]:
            if key in fts_by_key:
                out.append(fts_by_key[key])
            else:
                msg = self.repo.get(*key)
                if msg is not None:
                    out.append(SearchHit(message=msg, score=0.0, snippet=msg.text[:200] if msg.text else ""))
        return RetrievalResult(hits=out, method="hybrid")

    def _rowids_to_keys(self, rowids: list[int]) -> list[tuple[int, int]]:
        if not rowids:
            return []
        with self.repo._conn() as c:
            placeholders = ",".join("?" * len(rowids))
            rows = c.execute(
                f"SELECT rowid, chat_id, id FROM messages WHERE rowid IN ({placeholders})",
                rowids,
            ).fetchall()
        by_rowid = {r[0]: (r[1], r[2]) for r in rows}
        return [by_rowid[r] for r in rowids if r in by_rowid]
```

(Add a `MessageRepo.get(chat_id, id) -> Message | None` if not already present.)

### 7. `tgram/adapters/llm.py`

```python
import os
from dataclasses import dataclass
from typing import AsyncIterator

import litellm

# Map short names to LiteLLM model strings.
MODELS = {
    "qwen":    "ollama/qwen3.6:35b-a3b-q4_k_m",
    "claude":  "anthropic/claude-sonnet-4-7",
    "gpt":     "openai/gpt-4o",
    "gemini":  "gemini/gemini-2.0-pro",
    "kimi":    "openrouter/moonshotai/kimi-k2",
}
DEFAULT_MODEL = "qwen"


@dataclass(frozen=True)
class ChatMessage:
    role: str    # "system" | "user" | "assistant"
    content: str


class LLMRouter:
    def __init__(self, default: str = DEFAULT_MODEL):
        self.default = default
        # LiteLLM picks API keys from env: ANTHROPIC_API_KEY, OPENAI_API_KEY, etc.
        # For Ollama set OLLAMA_API_BASE if non-default.
        ollama_base = os.getenv("OLLAMA_API_BASE")
        if ollama_base:
            litellm.api_base = ollama_base

    def resolve(self, name: str | None) -> str:
        key = (name or self.default).lower()
        if key in MODELS:
            return MODELS[key]
        return name  # allow raw LiteLLM strings too

    async def complete(self, messages: list[ChatMessage], *, model: str | None = None,
                       max_tokens: int = 1024, temperature: float = 0.2) -> str:
        resp = await litellm.acompletion(
            model=self.resolve(model),
            messages=[{"role": m.role, "content": m.content} for m in messages],
            max_tokens=max_tokens,
            temperature=temperature,
        )
        return resp.choices[0].message.content

    async def stream(self, messages: list[ChatMessage], *, model: str | None = None,
                     max_tokens: int = 1024, temperature: float = 0.2
                     ) -> AsyncIterator[str]:
        stream = await litellm.acompletion(
            model=self.resolve(model),
            messages=[{"role": m.role, "content": m.content} for m in messages],
            max_tokens=max_tokens,
            temperature=temperature,
            stream=True,
        )
        async for chunk in stream:
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta
```

### 8. `tgram/services/ai.py`

```python
from dataclasses import dataclass
from typing import AsyncIterator

from tgram.adapters.llm import ChatMessage, LLMRouter
from tgram.services.retrieval import Retriever, RetrievalResult


SYSTEM_PROMPT = """You are an assistant that answers questions strictly from
the provided Telegram chat excerpts. Cite the source of every claim using
[chat_id/message_id]. If the excerpts don't contain the answer, say so —
do not invent or hallucinate. Quote sparingly; prefer summarising in your
own words while keeping citations accurate."""


@dataclass
class Answer:
    text: str
    citations: list[tuple[int, int]]   # [(chat_id, message_id), …]
    method: str                         # retrieval method used


class AIService:
    def __init__(self, retriever: Retriever, llm: LLMRouter,
                 context_budget_chars: int = 50_000):
        self.retriever = retriever
        self.llm = llm
        self.budget = context_budget_chars

    async def ask(self, question: str, *, chat_id: int | None = None,
                  model: str | None = None, k: int = 30) -> Answer:
        rr = await self.retriever.retrieve(question, chat_id=chat_id, limit=k)
        ctx, cites = self._format_context(rr)
        msgs = [
            ChatMessage("system", SYSTEM_PROMPT),
            ChatMessage("user", f"<excerpts>\n{ctx}\n</excerpts>\n\nQuestion: {question}"),
        ]
        text = await self.llm.complete(msgs, model=model)
        return Answer(text=text, citations=cites, method=rr.method)

    async def stream_ask(self, question: str, *, chat_id: int | None = None,
                         model: str | None = None, k: int = 30
                         ) -> AsyncIterator[str]:
        rr = await self.retriever.retrieve(question, chat_id=chat_id, limit=k)
        ctx, _ = self._format_context(rr)
        msgs = [
            ChatMessage("system", SYSTEM_PROMPT),
            ChatMessage("user", f"<excerpts>\n{ctx}\n</excerpts>\n\nQuestion: {question}"),
        ]
        async for piece in self.llm.stream(msgs, model=model):
            yield piece

    def _format_context(self, rr: RetrievalResult) -> tuple[str, list[tuple[int, int]]]:
        lines: list[str] = []
        cites: list[tuple[int, int]] = []
        used = 0
        for h in rr.hits:
            m = h.message
            who = m.username or (str(m.from_user_id) if m.from_user_id else "anon")
            when = m.date.strftime("%Y-%m-%d %H:%M")
            text = (m.text or "").strip()
            line = f"[{m.chat_id}/{m.id}] {when} @{who}: {text}"
            if used + len(line) > self.budget:
                break
            lines.append(line)
            cites.append((m.chat_id, m.id))
            used += len(line) + 1
        return "\n".join(lines), cites
```

### 9. CLI subcommands

In `tgram/interfaces/cli.py`:

```python
ap = sub.add_parser("ask", help="Ask a question grounded in the archive")
ap.add_argument("question")
ap.add_argument("--chat", type=int, default=None)
ap.add_argument("--model", default=None,
                help="qwen | claude | gpt | gemini | kimi (or full LiteLLM model id)")
ap.add_argument("-k", type=int, default=30, help="messages to retrieve")

sub.add_parser("web", help="Launch Gradio chat UI")

emb = sub.add_parser("embed", help="Manually drain the embedding queue")
emb.add_argument("--max-batches", type=int, default=100)
```

Handlers:

```python
elif args.cmd == "ask":
    from tgram.adapters.embeddings import OllamaEmbedder, EMBED_MODEL
    from tgram.adapters.llm import LLMRouter
    from tgram.adapters.search_fts import FTSSearch
    from tgram.adapters.vector_store import VectorStore
    from tgram.services.ai import AIService
    from tgram.services.retrieval import Retriever

    embedder = OllamaEmbedder()
    fts = FTSSearch(cfg.db_path)
    vec = VectorStore(cfg.db_path, EMBED_MODEL)
    retr = Retriever(fts, vec, embedder, repo)
    ai = AIService(retr, LLMRouter())
    answer = await ai.ask(args.question, chat_id=args.chat, model=args.model, k=args.k)
    print(answer.text)
    print()
    print(f"— retrieval: {answer.method}, {len(answer.citations)} citation(s)")

elif args.cmd == "embed":
    from tgram.adapters.embeddings import OllamaEmbedder, EMBED_MODEL
    from tgram.adapters.vector_store import VectorStore
    from tgram.services.embed_worker import EmbedWorker

    worker = EmbedWorker(cfg.db_path, OllamaEmbedder(), VectorStore(cfg.db_path, EMBED_MODEL))
    n = await worker.drain(max_batches=args.max_batches)
    print(f"Embedded {n} message(s).")

elif args.cmd == "web":
    from tgram.interfaces.web import launch
    launch(cfg)
```

### 10. `tgram/interfaces/web.py` (Gradio)

```python
import asyncio
import gradio as gr

from tgram.adapters.embeddings import OllamaEmbedder, EMBED_MODEL
from tgram.adapters.llm import LLMRouter, MODELS
from tgram.adapters.repo_messages import MessageRepo
from tgram.adapters.search_fts import FTSSearch
from tgram.adapters.vector_store import VectorStore
from tgram.config import Config
from tgram.services.ai import AIService
from tgram.services.retrieval import Retriever


def launch(cfg: Config):
    repo = MessageRepo(cfg.db_path)
    embedder = OllamaEmbedder()
    fts = FTSSearch(cfg.db_path)
    vec = VectorStore(cfg.db_path, EMBED_MODEL)
    ai = AIService(Retriever(fts, vec, embedder, repo), LLMRouter())

    async def respond(message, history, model_choice):
        partial = ""
        async for chunk in ai.stream_ask(message, model=model_choice):
            partial += chunk
            yield partial

    with gr.Blocks(title="tgram") as app:
        gr.Markdown("## tgram — chat with your Telegram archive")
        model_dd = gr.Dropdown(
            choices=list(MODELS.keys()), value="qwen", label="Model"
        )
        chat = gr.ChatInterface(fn=respond, additional_inputs=[model_dd], type="messages")

    app.launch(server_name="0.0.0.0", server_port=7860, share=False)
```

### 11. Daemon integration

In `tgram/interfaces/daemon.py`, add a periodic embed-drain job:

```python
from tgram.adapters.embeddings import OllamaEmbedder, EMBED_MODEL
from tgram.adapters.vector_store import VectorStore
from tgram.services.embed_worker import EmbedWorker

# inside run_daemon, after svc construction:
embedder = OllamaEmbedder()
worker = EmbedWorker(cfg.db_path, embedder, VectorStore(cfg.db_path, EMBED_MODEL))

await scheduler.add_schedule(
    worker.drain,
    IntervalTrigger(minutes=int(os.getenv("EMBED_INTERVAL_MINUTES", "2"))),
    id="embed_drain",
)
```

### 12. `.env` additions

```text
# Default LLM
LLM_DEFAULT_MODEL=qwen           # qwen | claude | gpt | gemini | kimi

# API keys (set whichever providers you use)
ANTHROPIC_API_KEY=
OPENAI_API_KEY=
GEMINI_API_KEY=
OPENROUTER_API_KEY=

# Ollama (local)
OLLAMA_API_BASE=http://localhost:11434

# Embedding worker cadence
EMBED_INTERVAL_MINUTES=2
```

### 13. Backfill embeddings for existing data

`tgram/migrations/006_embed_backfill.py`:

```python
"""One-shot: enqueue every existing text message for embedding."""
import sqlite3
from tgram.config import Config


def main():
    cfg = Config.load()
    with sqlite3.connect(cfg.db_path) as conn:
        conn.execute(
            """INSERT OR IGNORE INTO embedding_queue (message_rowid)
               SELECT rowid FROM messages WHERE text IS NOT NULL AND length(text) >= 5"""
        )
        n = conn.execute("SELECT COUNT(*) FROM embedding_queue").fetchone()[0]
        conn.commit()
    print(f"Queued {n} message(s) for embedding. Run `python -m tgram embed` (or start daemon).")


if __name__ == "__main__":
    main()
```

## Acceptance criteria

1. **Schema applied:**
   ```bash
   sqlite3 data/messages.db ".schema message_vectors"
   sqlite3 data/messages.db ".schema message_vector_map"
   ```

2. **Embedding worker drains queue:**
   ```bash
   python -m tgram.migrations.006_embed_backfill
   python -m tgram embed --max-batches 5
   sqlite3 data/messages.db "SELECT COUNT(*) FROM message_vector_map"
   ```
   Count grows after each `embed` invocation.

3. **Ollama models reachable:**
   ```bash
   ollama list | grep -E "qwen3.6:35b-a3b-q4_k_m|nomic-embed-text-v2-moe"
   ```
   Both rows present.

4. **Local Q&A works (no external API keys needed):**
   ```bash
   python -m tgram ask "summarise the most recent discussion"
   ```
   Returns a coherent answer with at least one `[chat_id/message_id]` citation. Citations resolvable via:
   ```bash
   sqlite3 data/messages.db "SELECT text FROM messages WHERE chat_id=<X> AND id=<Y>"
   ```

5. **Cloud LLM routing works (if keys are configured):**
   ```bash
   ANTHROPIC_API_KEY=... python -m tgram ask "..." --model claude
   OPENAI_API_KEY=... python -m tgram ask "..." --model gpt
   ```
   Each completes successfully via LiteLLM.

6. **Gradio chat UI:**
   ```bash
   python -m tgram web
   ```
   Browser opens at http://localhost:7860, model dropdown lists qwen/claude/gpt/gemini/kimi, asking a question streams a response.

7. **Daemon embed-drain integration:**
   - Start daemon, wait one `EMBED_INTERVAL_MINUTES` cycle.
   - Verify `embedding_queue` shrinks and `message_vector_map` grows.

8. **Hybrid retrieval beats FTS-only on a fuzzy query:**
   - Ask a question whose answer doesn't share vocabulary with the underlying messages (e.g. "what frustrated people?" vs. messages saying "annoying", "hate", "broken").
   - Retrieved hits should include semantically-related messages, not just keyword matches.

9. **Citations are real:**
   - Every `[chat_id/message_id]` in an answer must resolve to a row in the `messages` table.

10. **Multilingual works:**
    - Ask a question in Russian over a Russian-language channel; answer is grounded and cites real messages. (`nomic-embed-text-v2-moe` is multilingual.)

## Out of scope

- Re-ranking with a cross-encoder (overkill for personal scale)
- Citation rendering with clickable links (CLI only — Gradio shows raw text)
- Conversation memory across `ask` invocations (each ask is independent)
- Cost tracking / usage logs (LiteLLM offers this; defer)
- Fine-tuning, prompt caching, evaluation harnesses

## Gotchas

- **sqlite-vec extension loading:** Every connection that touches `message_vectors` must call `sqlite_vec.load(conn)`. The `MessageRepo._conn` change in step 2 handles this for message-related code; reuse `VectorStore._conn` everywhere else.
- **Embedding model dimension:** `nomic-embed-text-v2-moe` is 768-dim. The schema hardcodes 768. If swapping models, change `EMBED_DIM` and recreate `message_vectors` (the table can't be altered for dim).
- **LiteLLM Ollama model strings:** Use `ollama/<model_tag>` exactly as it appears in `ollama list`. Trailing `:latest` is required if the local tag has it.
- **Anthropic model name:** As of May 2026, the latest Sonnet identifier in LiteLLM is `anthropic/claude-sonnet-4-7`. Verify against `litellm --supported_models` if it errors.
- **Gradio version:** v5+ uses `type="messages"` for the OpenAI-style message format. Older guides showing `type="tuples"` are deprecated.
- **First-run latency for Qwen 35B-A3B:** First completion after a cold Ollama start can take 30–60s while the model is loaded into VRAM. Subsequent completions are fast. The Gradio UI's streaming hides this, but CLI users may think it hung — log a startup hint.
- **Long messages:** No chunking is implemented in this phase. A single very long message is embedded as one vector. For most chat content this is fine. If you hit messages >2000 chars often, add a simple sentence-split chunker in `EmbedWorker` later.
- **RRF scoring:** k=60 is the standard default from the original RRF paper. If retrieval feels skewed too much toward FTS or too much toward vectors, tune K_RRF, but expect 60 to be near-optimal.
