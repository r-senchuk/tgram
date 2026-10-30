from datetime import datetime
from pathlib import Path
import pytest

from tgram.adapters.repo_channels import ChannelRepo
from tgram.adapters.repo_messages import MessageRepo
from tgram.adapters.repo_topics import TopicRepo
from tgram.domain.channel import Channel
from tgram.domain.topic import Topic
from tests.conftest import make_message


def test_message_repo_crud_and_queries(tmp_path: Path):
    db = tmp_path / "messages.db"
    repo = MessageRepo(db)

    # empty
    assert repo.count(1) == 0
    assert repo.min_id(1) is None
    assert repo.max_id(1) is None
    assert repo.existing_ids(1, {1, 2}) == set()
    assert repo.find_gaps(1) == []

    # Insert messages with a gap: 10, 11, 15
    m10 = make_message(10, chat_id=1, virtual_topic_id=10)
    m11 = make_message(11, chat_id=1, reply_to_message_id=10, virtual_topic_id=10)
    m15 = make_message(15, chat_id=1, virtual_topic_id=15)
    repo.save_many([m10, m11, m15])

    assert repo.count(1) == 3
    assert repo.min_id(1) == 10
    assert repo.max_id(1) == 15
    assert repo.exists(1, 10) is True
    assert repo.exists(1, 12) is False
    assert repo.existing_ids(1, {10, 11, 12, 15}) == {10, 11, 15}

    # Gaps check
    gaps = repo.find_gaps(1)
    assert gaps == [(12, 14)]

    # Thread root resolution in repo
    assert repo.thread_root_of(1, 11) == 10
    assert repo.thread_root_of(1, 10) == 10
    assert repo.thread_root_of(1, 999) == 999

    # Get by id
    row = repo.get_by_id(10, chat_id=1)
    assert row is not None
    assert row["id"] == 10
    assert row["virtual_topic_id"] == 10


def test_topic_repo(tmp_path: Path):
    db = tmp_path / "topics.db"
    msg_repo = MessageRepo(db)
    topic_repo = TopicRepo(db)

    # Insert message in forum topic 100
    m = make_message(105, chat_id=1, reply_to_top_message_id=100)
    msg_repo.save(m)

    # unknown_topic_ids before syncing
    unknown = topic_repo.unknown_topic_ids(1)
    assert 100 in unknown

    # Save topic
    topic_repo.save(Topic(chat_id=1, topic_id=100, title="General Discussion"))

    unknown = topic_repo.unknown_topic_ids(1)
    assert 100 not in unknown

    stats = topic_repo.stats_for_chat(1)
    assert len(stats) == 1
    assert stats[0]["topic_id"] == 100
    assert stats[0]["title"] == "General Discussion"
    assert stats[0]["msg_count"] == 1


def test_channel_repo(tmp_path: Path):
    db = tmp_path / "channels.db"
    # init tables via MessageRepo
    MessageRepo(db)
    repo = ChannelRepo(db)

    assert repo.list_all() == []
    assert repo.list_enabled() == []

    repo.upsert(Channel(chat_id=10, title="Channel A", type="channel", is_forum=False))
    repo.upsert(Channel(chat_id=20, title="Channel B", type="supergroup", is_forum=True))

    channels = repo.list_all()
    assert len(channels) == 2

    # Enable channel 10
    repo.set_enabled(10, enabled=True)
    assert [ch.chat_id for ch in repo.list_enabled()] == [10]

    # Disable channel 10
    repo.set_enabled(10, enabled=False)
    assert repo.list_enabled() == []
