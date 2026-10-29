from tgram.adapters.llm_ollama import OllamaAdapter
from tgram.adapters.search_fts import FTSSearch, SearchHit

SYSTEM_PROMPT = """You are an assistant that answers questions based strictly on
excerpts from a Telegram group chat archive. Excerpts are grouped into chronological
conversation threads (--- [topic] YYYY-MM-DD ---) with ↳ indicating replies.
Cite your sources using [msg:<id>]. Always use a separate bracket per message:
[msg:123] [msg:456] — never combine multiple IDs in one bracket like [msg:123, msg:456].
If the provided excerpts don't contain enough information to answer, say so —
do not invent facts. Answer in the same language as the question."""

DEFAULT_CONTEXT_CHARS = 12_000


class AIService:
    def __init__(self, fts: FTSSearch, llm, embedder=None):
        self.fts = fts
        self.llm = llm
        # embedder can be passed explicitly (e.g. always-on Ollama with a cloud chat LLM)
        self._embedder: OllamaAdapter | None = (
            embedder or (llm if isinstance(llm, OllamaAdapter) else None)
        )

    def ask(
        self,
        question: str,
        *,
        chat_id: int | None = None,
        topic_id: int | None = None,
        limit: int = 30,
        stream: bool = True,
        think: bool = True,
    ):
        """Single-turn Q&A. Returns (response, hits, context_index)."""
        return self.ask_with_history(
            question, [],
            chat_id=chat_id, topic_id=topic_id,
            limit=limit, stream=stream, think=think,
        )

    def ask_with_history(
        self,
        question: str,
        history: list[tuple[str, str]],
        *,
        chat_id: int | None = None,
        topic_id: int | None = None,
        limit: int = 30,
        stream: bool = True,
        think: bool = True,
    ):
        """Multi-turn Q&A with conversation history.

        history — list of (user_message, assistant_message) prior turns.
        Archive context is retrieved fresh for the current question; prior turns
        are replayed so the model can resolve pronouns and references.
        Returns (response, hits, context_index).
        """
        query_vector: list[float] | None = None
        if self._embedder and self.fts.embedding_repo:
            try:
                query_vector = self._embedder.embed(["search_query: " + question])[0]
            except Exception:
                pass  # embedding failure degrades gracefully to FTS-only

        hits = self.fts.search(
            question, chat_id=chat_id, topic_id=topic_id,
            limit=limit, match_any=True, query_vector=query_vector,
        )
        context, context_index = self._build_context(hits)

        messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]

        if not history:
            # First turn: embed archive in the user message
            messages.append({
                "role": "user",
                "content": f"<archive>\n{context}\n</archive>\n\n{question}",
            })
        else:
            # Replay history with archive context on the first turn only
            first_q, first_a = history[0]
            messages.append({
                "role": "user",
                "content": f"<archive>\n{context}\n</archive>\n\n{first_q}",
            })
            messages.append({"role": "assistant", "content": first_a})
            for user_msg, asst_msg in history[1:]:
                messages.append({"role": "user",      "content": user_msg})
                messages.append({"role": "assistant",  "content": asst_msg})
            messages.append({"role": "user", "content": question})

        response = self.llm.chat(messages, stream=stream, think=think)
        return response, hits, context_index

    def _build_context(self, hits: list[SearchHit]) -> tuple[str, dict[int, tuple[int, int]]]:
        budget = getattr(self.llm, "context_chars", DEFAULT_CONTEXT_CHARS)
        seen_threads: set[tuple[int, int]] = set()
        context_index: dict[int, tuple[int, int]] = {}
        blocks: list[str] = []
        used = 0

        for h in hits:
            vtid = h.virtual_topic_id if getattr(h, "virtual_topic_id", None) is not None else h.message_id
            thread_key = (h.chat_id, vtid)
            if thread_key in seen_threads:
                continue
            seen_threads.add(thread_key)

            conv = self.fts.get_conversation(h, max_thread_msgs=10, window=1)
            if not conv:
                continue

            topic_label = h.topic_title or "General"
            first_date = (
                conv[0].date[:10]
                if (conv[0].date and len(conv[0].date) >= 10)
                else (h.date[:10] if h.date else "")
            )
            header = f"--- [{topic_label}] {first_date} ---"

            block_lines: list[str] = [header]
            block_msg_ids: set[int] = set()
            added_msgs: list = []

            for m in conv:
                if getattr(m, "skipped_before", 0) > 0:
                    block_lines.append(f"  … {m.skipped_before} earlier message(s) in thread …")
                who = f"@{m.username}" if m.username else f"user:{m.from_user_id}"
                time_str = m.date[11:16] if (m.date and len(m.date) >= 16) else (m.date or "")
                reply_to = getattr(m, "reply_to_message_id", None)
                prefix = f"↳ [reply to msg:{reply_to}] " if (reply_to and reply_to in block_msg_ids) else ""
                line = f"[msg:{m.message_id}] {time_str} {who}: {prefix}{m.text or ''}"
                block_lines.append(line)
                block_msg_ids.add(m.message_id)
                added_msgs.append(m)

            block_str = "\n".join(block_lines)
            sep_len = 2 if blocks else 0

            if blocks:
                if used + sep_len + len(block_str) > budget:
                    break
                blocks.append(block_str)
                used += sep_len + len(block_str)
                for m in added_msgs:
                    cid = getattr(m, "chat_id", None) or h.chat_id
                    context_index[m.message_id] = (cid, m.message_id)
                context_index[h.message_id] = (h.chat_id, h.message_id)
            else:
                if len(block_str) > budget:
                    truncated_lines = [header]
                    current_len = len(header)
                    for line in block_lines[1:]:
                        if current_len + 1 + len(line) > budget:
                            break
                        truncated_lines.append(line)
                        current_len += 1 + len(line)
                    block_str = "\n".join(truncated_lines)
                    blocks.append(block_str)
                    used = len(block_str)
                    for m in added_msgs:
                        if f"[msg:{m.message_id}]" in block_str:
                            cid = getattr(m, "chat_id", None) or h.chat_id
                            context_index[m.message_id] = (cid, m.message_id)
                    context_index[h.message_id] = (h.chat_id, h.message_id)
                else:
                    blocks.append(block_str)
                    used = len(block_str)
                    for m in added_msgs:
                        cid = getattr(m, "chat_id", None) or h.chat_id
                        context_index[m.message_id] = (cid, m.message_id)
                    context_index[h.message_id] = (h.chat_id, h.message_id)

        return "\n\n".join(blocks), context_index
