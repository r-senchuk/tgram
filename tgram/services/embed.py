import logging

from tgram.adapters.llm_ollama import OllamaAdapter, EMBED_MODEL
from tgram.adapters.repo_embeddings import EmbeddingRepo

# nomic-embed-text-v2-moe: 512-token context window.
# Dense Cyrillic text tokenises at ~2 tokens/char, so 400 chars ≈ safe upper bound.
_MAX_CHARS = 400
_OVERLAP   = 50

_DOC_PREFIX = "search_document: "


def _chunk_text(text: str) -> list[str]:
    if len(text) <= _MAX_CHARS:
        return [_DOC_PREFIX + text]
    chunks = []
    start = 0
    while start < len(text):
        chunks.append(_DOC_PREFIX + text[start:start + _MAX_CHARS])
        start += _MAX_CHARS - _OVERLAP
    return chunks


class EmbedService:
    def __init__(self, ollama: OllamaAdapter, repo: EmbeddingRepo):
        self.ollama = ollama
        self.repo = repo

    def _embed_message(self, chat_id: int, msg_id: int, text: str) -> list[tuple]:
        """Embed all chunks of one message. Returns [] on failure."""
        chunks = _chunk_text(text)
        try:
            vectors = self.ollama.embed(chunks)
            return [(chat_id, msg_id, idx, vec, EMBED_MODEL)
                    for idx, vec in enumerate(vectors)]
        except Exception:
            print(f"\n  [skip] msg {msg_id} failed to embed ({len(text)} chars)")
            return []

    def _embed_safe(self, batch: list[tuple]) -> list[tuple]:
        """Embed a batch of messages with per-message retry on failure."""
        all_chunks: list[str] = []
        index: list[tuple[int, int, int]] = []  # (chat_id, msg_id, chunk_idx)
        for chat_id, msg_id, text in batch:
            for chunk_idx, chunk in enumerate(_chunk_text(text)):
                all_chunks.append(chunk)
                index.append((chat_id, msg_id, chunk_idx))

        try:
            vectors = self.ollama.embed(all_chunks)
            return [(chat_id, msg_id, chunk_idx, vec, EMBED_MODEL)
                    for (chat_id, msg_id, chunk_idx), vec in zip(index, vectors)]
        except Exception as exc:
            logging.warning("Batch embed failed, retrying per-message: %s", exc)

        rows = []
        for chat_id, msg_id, text in batch:
            rows.extend(self._embed_message(chat_id, msg_id, text))
        return rows

    def backfill(
        self,
        chat_id: int | None = None,
        batch_size: int = 100,
        max_batches: int | None = None,
        quiet: bool = False,
    ) -> int:
        """Embed messages that lack embeddings. Returns total count embedded."""
        total = self.repo.count_missing(chat_id, EMBED_MODEL)
        if total == 0:
            if not quiet:
                print("All messages already embedded.")
            return 0

        if not quiet:
            print(f"Embedding {total:,} messages in batches of {batch_size}…")
        done = saved = batches = 0
        while True:
            if max_batches is not None and batches >= max_batches:
                break
            batch = self.repo.ids_without_embeddings(chat_id, EMBED_MODEL, limit=batch_size)
            if not batch:
                break

            rows = self._embed_safe(batch)
            if rows:
                self.repo.save_many(rows)
            saved += len(rows)
            done  += len(batch)
            batches += 1
            if not quiet:
                print(f"  {done:,} / {total:,}", end="\r", flush=True)

        if not quiet:
            print(f"\nDone. Embedded {saved:,} messages.")
        return saved
