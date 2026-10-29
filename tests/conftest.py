from datetime import datetime
from pathlib import Path
import pytest

from tgram.adapters.repo_embeddings import EmbeddingRepo
from tgram.adapters.repo_messages import MessageRepo
from tgram.adapters.search_fts import FTSSearch
from tgram.domain.message import Message


def make_message(
    id: int,
    chat_id: int = 1,
    date: datetime | None = None,
    text: str | None = "sample text",
    from_user_id: int | None = 100,
    username: str | None = "alice",
    reply_to_message_id: int | None = None,
    reply_to_top_message_id: int | None = None,
    virtual_topic_id: int | None = None,
    media_type: str | None = None,
    raw_json: str = "{}",
) -> Message:
    return Message(
        chat_id=chat_id,
        id=id,
        date=date or datetime(2026, 1, 1, 12, 0, 0),
        text=text,
        from_user_id=from_user_id,
        username=username,
        reply_to_message_id=reply_to_message_id,
        reply_to_top_message_id=reply_to_top_message_id,
        virtual_topic_id=virtual_topic_id,
        media_type=media_type,
        raw_json=raw_json,
    )


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "test.db"


@pytest.fixture
def message_repo(db_path: Path) -> MessageRepo:
    return MessageRepo(db_path)


@pytest.fixture
def embedding_repo(db_path: Path) -> EmbeddingRepo:
    return EmbeddingRepo(db_path)


@pytest.fixture
def fts_search(db_path: Path, embedding_repo: EmbeddingRepo) -> FTSSearch:
    return FTSSearch(db_path, embedding_repo=embedding_repo)
