import re
from tgram.adapters.search_fts import FTSSearch, SearchHit

_FTS_OP_RE = re.compile(r'"|\w\*')


def has_fts_operators(query: str) -> bool:
    """Return True if query uses explicit FTS phrase quotes or prefix wildcard."""
    return bool(_FTS_OP_RE.search(query))


class SearchService:
    def __init__(self, fts: FTSSearch, embedder=None):
        self.fts = fts
        self.embedder = embedder

    def search(
        self,
        query: str,
        *,
        semantic: bool = True,
        **filters,
    ) -> tuple[list[SearchHit], str]:
        """Run search and return (hits, mode_description)."""
        query_vector = None
        if not semantic or not self.embedder or not self.fts.embedding_repo:
            mode = "fts"
        elif has_fts_operators(query):
            mode = "fts (operators)"
        else:
            try:
                query_vector = self.embedder.embed(["search_query: " + query])[0]
                mode = "hybrid"
            except Exception:
                mode = "fts (ollama unreachable)"

        hits = self.fts.search(query, query_vector=query_vector, **filters)
        return hits, mode

    def rebuild_index(self) -> int:
        return self.fts.rebuild()
