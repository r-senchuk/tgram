from tgram.adapters.llm_ollama import OllamaAdapter
from tgram.adapters.search_fts import FTSSearch, SearchHit

SYSTEM_PROMPT = """You are an assistant that answers questions based strictly on
excerpts from a Telegram group chat archive. Each excerpt shows the date, sender
username, topic name, and message text. Cite your sources using [msg:<id>].
Always use a separate bracket per message: [msg:123] [msg:456] — never combine
multiple IDs in one bracket like [msg:123, msg:456].
If the provided excerpts don't contain enough information to answer, say so —
do not invent facts. Answer in the same language as the question."""

CONTEXT_BUDGET = 8_000  # max chars of message context to include in the prompt


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
        """Single-turn Q&A. Returns (response, hits)."""
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
        are replayed so Qwen can resolve pronouns and references.
        Returns (response, hits).
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
        context = self._build_context(hits)

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
        return response, hits

    def _build_context(self, hits: list[SearchHit]) -> str:
        lines: list[str] = []
        used = 0
        for h in hits:
            who   = f"@{h.username}" if h.username else f"user:{h.from_user_id}"
            topic = f" [{h.topic_title}]" if h.topic_title else ""
            line  = f"[msg:{h.message_id}] {h.date[:16]}{topic} {who}: {h.text}"
            if used + len(line) > CONTEXT_BUDGET:
                break
            lines.append(line)
            used += len(line) + 1
        return "\n".join(lines)
