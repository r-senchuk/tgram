import sqlite3
from pathlib import Path
import pytest

from tgram.adapters.repo_messages import MessageRepo
from tgram.adapters.search_fts import FTSSearch
from tests.conftest import make_message


def test_thread_invariants_in_isolation(tmp_path: Path):
    """Verify that thread invariants hold in an isolated scenario:
    1. Top-level message has virtual_topic_id == id.
    2. Forum topic starter (reply_to_message_id == reply_to_top_message_id) has virtual_topic_id == id.
    3. Normal reply (reply_to_message_id != reply_to_top_message_id) inherits parent's virtual_topic_id.
    4. Multi-hop reply chain inherits root's virtual_topic_id.
    """
    db_path = tmp_path / "invariants.db"
    repo = MessageRepo(db_path)

    # 1. Non-forum top-level
    m1 = make_message(10, chat_id=1, virtual_topic_id=10)

    # 2. Forum topic post (reply_to_top_id == reply_to_id == 5)
    m2 = make_message(20, chat_id=1, reply_to_message_id=5, reply_to_top_message_id=5, virtual_topic_id=20)

    # 3. Direct reply to m2
    m3 = make_message(21, chat_id=1, reply_to_message_id=20, reply_to_top_message_id=5, virtual_topic_id=20)

    # 4. Multi-hop reply to m3
    m4 = make_message(22, chat_id=1, reply_to_message_id=21, reply_to_top_message_id=5, virtual_topic_id=20)

    repo.save_many([m1, m2, m3, m4])

    # Assert invariant 1: no child points to a wrong virtual_topic_id
    with sqlite3.connect(db_path) as conn:
        mismatched_replies = conn.execute(
            """SELECT count(*) FROM messages c
               JOIN messages p ON c.chat_id = p.chat_id AND c.reply_to_message_id = p.id
               WHERE (c.reply_to_top_message_id IS NULL OR c.reply_to_message_id != c.reply_to_top_message_id)
                 AND c.virtual_topic_id != p.virtual_topic_id"""
        ).fetchone()[0]
        assert mismatched_replies == 0

        # Assert invariant 2: forum thread starters are rooted at themselves
        forum_starters_misrouted = conn.execute(
            """SELECT count(*) FROM messages
               WHERE reply_to_top_message_id IS NOT NULL
                 AND reply_to_message_id = reply_to_top_message_id
                 AND virtual_topic_id != id"""
        ).fetchone()[0]
        assert forum_starters_misrouted == 0

        # Assert invariant 3: non-forum roots are rooted at themselves
        non_forum_roots_misrouted = conn.execute(
            """SELECT count(*) FROM messages
               WHERE reply_to_message_id IS NULL
                 AND virtual_topic_id != id"""
        ).fetchone()[0]
        assert non_forum_roots_misrouted == 0


def test_fts_rebuild_and_match(tmp_path: Path):
    db_path = tmp_path / "fts_test.db"
    repo = MessageRepo(db_path)
    fts = FTSSearch(db_path)

    m1 = make_message(1, chat_id=1, text="FastAPI backend framework")
    m2 = make_message(2, chat_id=1, text="Ruby on Rails web framework")
    m3 = make_message(3, chat_id=1, text="Frontend React and TypeScript")
    repo.save_many([m1, m2, m3])

    rebuilt = fts.rebuild()
    assert rebuilt == 3

    hits = fts.search("FastAPI")
    assert len(hits) == 1
    assert hits[0].message_id == 1

    hits_framework = fts.search("framework")
    assert len(hits_framework) == 2
    assert {h.message_id for h in hits_framework} == {1, 2}
