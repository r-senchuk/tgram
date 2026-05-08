from tgram.adapters.search_fts import FTSSearch, SearchHit


class SearchService:
    def __init__(self, fts: FTSSearch):
        self.fts = fts

    def search(self, query: str, **filters) -> list[SearchHit]:
        return self.fts.search(query, **filters)

    def rebuild_index(self) -> int:
        return self.fts.rebuild()
