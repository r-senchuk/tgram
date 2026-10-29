from datetime import datetime, timedelta
from tgram.adapters.repo_messages import MessageRepo
from tgram.adapters.search_fts import FTSSearch, SearchHit
from tests.conftest import make_message


def test_40_message_thread(message_repo: MessageRepo, fts_search: FTSSearch):
    base_dt = datetime(2026, 1, 1, 12, 0, 0)
    msgs = []

    # 40-message thread: virtual_topic_id=1
    # Ancestor chain of #20: 1 -> 5 -> 10 -> 15 -> 20
    # Direct replies to #20: 21, 22
    for i in range(1, 41):
        if i in (5, 10, 15, 20):
            reply_to = i - 5
        elif i in (21, 22):
            reply_to = 20
        else:
            reply_to = 1 if i > 1 else None

        msgs.append(
            make_message(
                id=i,
                date=base_dt + timedelta(minutes=i),
                text=f"Thread message {i}",
                reply_to_message_id=reply_to,
                reply_to_top_message_id=None,
                virtual_topic_id=1,
            )
        )
    message_repo.save_many(msgs)

    hit = SearchHit(
        chat_id=1,
        message_id=20,
        date=(base_dt + timedelta(minutes=20)).isoformat(),
        text="Thread message 20",
        username="alice",
        from_user_id=100,
        topic_id=None,
        topic_title=None,
        snippet="Thread message 20",
        virtual_topic_id=1,
        reply_to_message_id=15,
    )

    conv = fts_search.get_conversation(hit, max_thread_msgs=12, window=0)
    msg_ids = [m.message_id for m in conv]

    # Max thread msgs enforced
    assert len(conv) <= 12

    # ALWAYS keeps the root (1)
    assert 1 in msg_ids

    # ALWAYS keeps the ancestor path (1, 5, 10, 15)
    for ancestor_id in (1, 5, 10, 15):
        assert ancestor_id in msg_ids

    # ALWAYS keeps the hit itself (#20) with is_hit=True
    hit_msg = next(m for m in conv if m.message_id == 20)
    assert hit_msg.is_hit is True
    # All other messages have is_hit=False
    assert all(m.is_hit is False for m in conv if m.message_id != 20)

    # ALWAYS keeps direct replies (#21, #22)
    assert 21 in msg_ids
    assert 22 in msg_ids

    # Sets skipped_before > 0 where thread messages were omitted
    skipped_messages = [m for m in conv if m.skipped_before > 0]
    assert len(skipped_messages) > 0
    # For instance, message 5 should report that messages 2, 3, 4 were skipped
    msg_5 = next(m for m in conv if m.message_id == 5)
    assert msg_5.skipped_before == 3


def test_general_topic_scoping(message_repo: MessageRepo, fts_search: FTSSearch):
    base_dt = datetime(2026, 1, 1, 12, 0, 0)

    # General topic messages (reply_to_top_message_id IS NULL)
    m101 = make_message(id=101, date=base_dt, text="gen before", reply_to_top_message_id=None, virtual_topic_id=101)
    m103 = make_message(id=103, date=base_dt + timedelta(minutes=2), text="gen hit", reply_to_top_message_id=None, virtual_topic_id=103)
    m105 = make_message(id=105, date=base_dt + timedelta(minutes=4), text="gen after", reply_to_top_message_id=None, virtual_topic_id=105)

    # Topic 55 messages (reply_to_top_message_id = 55) chronologically interleaved
    m102 = make_message(id=102, date=base_dt + timedelta(minutes=1), text="topic 55 msg", reply_to_top_message_id=55, virtual_topic_id=102)
    m104 = make_message(id=104, date=base_dt + timedelta(minutes=3), text="topic 55 msg 2", reply_to_top_message_id=55, virtual_topic_id=104)

    message_repo.save_many([m101, m102, m103, m104, m105])

    hit = SearchHit(
        chat_id=1,
        message_id=103,
        date=m103.date.isoformat(),
        text="gen hit",
        username="alice",
        from_user_id=100,
        topic_id=None,  # General topic
        topic_title=None,
        snippet="gen hit",
        virtual_topic_id=103,
    )

    # 1. get_context should strictly pull from General topic (reply_to_top_message_id IS NULL)
    ctx = fts_search.get_context(hit, before=2, after=2)
    ctx_ids = [m.message_id for m in ctx]
    assert ctx_ids == [101, 103, 105]
    assert 102 not in ctx_ids
    assert 104 not in ctx_ids

    # 2. get_conversation should strictly pull window neighbours from General topic
    conv = fts_search.get_conversation(hit, max_thread_msgs=12, window=2)
    conv_ids = [m.message_id for m in conv]
    assert 101 in conv_ids
    assert 105 in conv_ids
    assert 102 not in conv_ids
    assert 104 not in conv_ids


def test_temporal_window_30_min_bound(message_repo: MessageRepo, fts_search: FTSSearch):
    base_dt = datetime(2026, 1, 1, 12, 0, 0)

    # Hit: Msg 50 at 12:00
    hit_msg = make_message(id=50, date=base_dt, text="hit", virtual_topic_id=50)

    # Different threads in the same topic (window candidates)
    # 20 min before (<= 30 min) -> included
    m_in_before = make_message(id=45, date=base_dt - timedelta(minutes=20), text="in before", virtual_topic_id=45)
    # 45 min before (> 30 min) -> excluded
    m_out_before = make_message(id=40, date=base_dt - timedelta(minutes=45), text="out before", virtual_topic_id=40)
    # 20 min after (<= 30 min) -> included
    m_in_after = make_message(id=55, date=base_dt + timedelta(minutes=20), text="in after", virtual_topic_id=55)
    # 45 min after (> 30 min) -> excluded
    m_out_after = make_message(id=60, date=base_dt + timedelta(minutes=45), text="out after", virtual_topic_id=60)

    message_repo.save_many([m_out_before, m_in_before, hit_msg, m_in_after, m_out_after])

    hit = SearchHit(
        chat_id=1,
        message_id=50,
        date=base_dt.isoformat(),
        text="hit",
        username="alice",
        from_user_id=100,
        topic_id=None,
        topic_title=None,
        snippet="hit",
        virtual_topic_id=50,
    )

    conv = fts_search.get_conversation(hit, max_thread_msgs=10, window=3, window_max_gap_min=30)
    conv_ids = [m.message_id for m in conv]

    assert 45 in conv_ids
    assert 55 in conv_ids
    assert 40 not in conv_ids
    assert 60 not in conv_ids


def test_deduplication_and_chronological_order(message_repo: MessageRepo, fts_search: FTSSearch):
    base_dt = datetime(2026, 1, 1, 12, 0, 0)

    # Message in thread that also falls within the temporal window
    m1 = make_message(id=10, date=base_dt, text="thread root", virtual_topic_id=10)
    m2 = make_message(id=11, date=base_dt + timedelta(minutes=5), text="thread hit", reply_to_message_id=10, virtual_topic_id=10)
    m3 = make_message(id=12, date=base_dt + timedelta(minutes=10), text="thread reply", reply_to_message_id=11, virtual_topic_id=10)
    # Message in other thread within window
    m4 = make_message(id=13, date=base_dt + timedelta(minutes=15), text="window msg", virtual_topic_id=13)

    message_repo.save_many([m1, m2, m3, m4])

    hit = SearchHit(
        chat_id=1,
        message_id=11,
        date=m2.date.isoformat(),
        text="thread hit",
        username="alice",
        from_user_id=100,
        topic_id=None,
        topic_title=None,
        snippet="thread hit",
        virtual_topic_id=10,
        reply_to_message_id=10,
    )

    conv = fts_search.get_conversation(hit, max_thread_msgs=10, window=3, window_max_gap_min=30)
    conv_ids = [m.message_id for m in conv]

    # Strictly unique message_ids (deduplicated)
    assert len(conv_ids) == len(set(conv_ids))

    # Strictly sorted in chronological / ascending message_id order
    assert conv_ids == sorted(conv_ids)
