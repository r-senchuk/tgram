import sqlite3
from tgram.adapters.repo_messages import MessageRepo
from tests.conftest import make_message


def test_repair_dry_run_and_apply(message_repo: MessageRepo, db_path):
    # 1. Top-level message (already correct)
    m1 = make_message(id=1, reply_to_message_id=None, reply_to_top_message_id=None, virtual_topic_id=1, text="first top level")
    # 2. Forum topic definition post (already correct)
    m100 = make_message(id=100, reply_to_message_id=None, reply_to_top_message_id=None, virtual_topic_id=100, text="topic header")
    # 3. Forum top-level post (wrongly rooted at top 100 instead of 101)
    m101 = make_message(id=101, reply_to_message_id=100, reply_to_top_message_id=100, virtual_topic_id=100, text="forum top post")
    # 4. Reply in forum to 101 (wrongly rooted at 100 instead of 101)
    m102 = make_message(id=102, reply_to_message_id=101, reply_to_top_message_id=100, virtual_topic_id=100, text="reply in forum")
    # 5. Multi-hop chain root (already correct)
    m201 = make_message(id=201, reply_to_message_id=None, reply_to_top_message_id=None, virtual_topic_id=201, text="chain root")
    # 6. Multi-hop 1-hop reply (already correct)
    m202 = make_message(id=202, reply_to_message_id=201, reply_to_top_message_id=None, virtual_topic_id=201, text="chain hop 1")
    # 7. Multi-hop 2-hop reply (wrongly 1-hop rooted at 202 instead of 201)
    m203 = make_message(id=203, reply_to_message_id=202, reply_to_top_message_id=None, virtual_topic_id=202, text="chain hop 2")
    # 8. Orphan reply to missing 999 (wrongly rooted at 1 instead of 999)
    m301 = make_message(id=301, reply_to_message_id=999, reply_to_top_message_id=None, virtual_topic_id=1, text="orphan msg")
    # 9. Reply to orphan 301 (wrongly rooted at 1 instead of 999)
    m302 = make_message(id=302, reply_to_message_id=301, reply_to_top_message_id=None, virtual_topic_id=1, text="reply to orphan")
    # 10. Cross-chat reply with reply_to_peer_id set (wrongly rooted at 888 instead of 401)
    m401 = make_message(
        id=401,
        reply_to_message_id=888,
        reply_to_top_message_id=None,
        virtual_topic_id=888,
        raw_json='{"reply_to": {"reply_to_peer_id": {"channel_id": 999}}}',
        text="cross chat reply",
    )

    all_msgs = [m1, m100, m101, m102, m201, m202, m203, m301, m302, m401]
    message_repo.save_many(all_msgs)

    # Check FTS initial count and searchability
    with sqlite3.connect(db_path) as conn:
        fts_count_initial = conn.execute("SELECT COUNT(*) FROM messages_fts").fetchone()[0]
        assert fts_count_initial == 10
        fts_match_forum = conn.execute("SELECT COUNT(*) FROM messages_fts WHERE messages_fts MATCH 'forum'").fetchone()[0]
        assert fts_match_forum == 2
        fts_match_orphan = conn.execute("SELECT COUNT(*) FROM messages_fts WHERE messages_fts MATCH 'orphan'").fetchone()[0]
        assert fts_match_orphan == 2

    # Test dry_run=True: exact expected count (6 rows need changing)
    expected_changes = 6
    changes = message_repo.repair_virtual_topics(dry_run=True)
    assert changes == expected_changes

    # Verify rows were NOT mutated in dry_run
    row101 = message_repo.get_by_id(101)
    assert row101["virtual_topic_id"] == 100

    row203 = message_repo.get_by_id(203)
    assert row203["virtual_topic_id"] == 202

    row401 = message_repo.get_by_id(401)
    assert row401["reply_to_message_id"] == 888
    assert row401["virtual_topic_id"] == 888

    # Test dry_run=False: returns the same count and applies mutations
    changes_real = message_repo.repair_virtual_topics(dry_run=False)
    assert changes_real == expected_changes

    # Verify expected virtual_topic_id values
    assert message_repo.get_by_id(101)["virtual_topic_id"] == 101
    assert message_repo.get_by_id(102)["virtual_topic_id"] == 101
    assert message_repo.get_by_id(203)["virtual_topic_id"] == 201
    assert message_repo.get_by_id(301)["virtual_topic_id"] == 999
    assert message_repo.get_by_id(302)["virtual_topic_id"] == 999

    # Cross-chat reply: reply_to_message_id cleared to NULL and virtual_topic_id is 401
    row401_after = message_repo.get_by_id(401)
    assert row401_after["reply_to_message_id"] is None
    assert row401_after["virtual_topic_id"] == 401

    # Idempotency: second run immediately returns 0
    second_run = message_repo.repair_virtual_topics(dry_run=False)
    assert second_run == 0

    # FTS integrity: verify row count is unchanged and MATCH queries still work
    with sqlite3.connect(db_path) as conn:
        fts_count_after = conn.execute("SELECT COUNT(*) FROM messages_fts").fetchone()[0]
        assert fts_count_after == fts_count_initial
        assert conn.execute("SELECT COUNT(*) FROM messages_fts WHERE messages_fts MATCH 'forum'").fetchone()[0] == 2
        assert conn.execute("SELECT COUNT(*) FROM messages_fts WHERE messages_fts MATCH 'orphan'").fetchone()[0] == 2


def test_repair_backfilled_parent(message_repo: MessageRepo):
    # Insert orphan reply id=50 (replying to missing id=40) and child id=60 (replying to 50)
    m50 = make_message(id=50, reply_to_message_id=40, virtual_topic_id=1, text="orphan 50")
    m60 = make_message(id=60, reply_to_message_id=50, virtual_topic_id=1, text="child 60")
    message_repo.save_many([m50, m60])

    message_repo.repair_virtual_topics()
    assert message_repo.get_by_id(50)["virtual_topic_id"] == 40
    assert message_repo.get_by_id(60)["virtual_topic_id"] == 40

    # Now insert parent id=40 (replying to root id=10) and root id=10
    m10 = make_message(id=10, reply_to_message_id=None, virtual_topic_id=10, text="root 10")
    m40 = make_message(id=40, reply_to_message_id=10, virtual_topic_id=10, text="parent 40")
    message_repo.save_many([m10, m40])

    # Re-run repair
    message_repo.repair_virtual_topics()

    # Verify 40, 50, and 60 all re-root to 10
    assert message_repo.get_by_id(10)["virtual_topic_id"] == 10
    assert message_repo.get_by_id(40)["virtual_topic_id"] == 10
    assert message_repo.get_by_id(50)["virtual_topic_id"] == 10
    assert message_repo.get_by_id(60)["virtual_topic_id"] == 10
