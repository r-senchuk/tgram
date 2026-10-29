from unittest.mock import MagicMock
from datetime import datetime

from tgram.domain.message import Message
from tgram.domain.threading import is_thread_start, resolve_root
from tgram.services.ingest import IngestService
from tests.conftest import make_message


def test_is_thread_start():
    # Top-level message
    assert is_thread_start(reply_to=None, top=None) is True
    # Top-level in a topic without explicit reply_to
    assert is_thread_start(reply_to=None, top=100) is True
    # Forum top-level post (reply_to == top)
    assert is_thread_start(reply_to=100, top=100) is True
    # Nested reply in forum topic
    assert is_thread_start(reply_to=105, top=100) is False
    # Nested reply in normal chat
    assert is_thread_start(reply_to=5, top=None) is False


def test_resolve_root_top_level():
    # Top-level message resolves to its own msg_id
    assert resolve_root(msg_id=42, reply_to=None, top=None, known_roots={}) == 42


def test_resolve_root_forum_top_level():
    # Forum top-level post (reply_to == top) resolves to its own msg_id
    assert resolve_root(msg_id=105, reply_to=100, top=100, known_roots={}) == 105


def test_resolve_root_nested_reply():
    # Nested reply (reply_to=105, top=100) with 105: 101 in known_roots -> 101
    known_roots = {105: 101}
    assert resolve_root(msg_id=110, reply_to=105, top=100, known_roots=known_roots) == 101


def test_resolve_root_multihop_chain():
    # Multi-hop chain resolution in order:
    # msg 1 (top-level) -> 1
    # msg 2 (reply to 1) -> 1
    # msg 3 (reply to 2) -> 1
    # msg 4 (reply to 3) -> 1
    roots: dict[int, int] = {}
    chain = [
        (1, None, None),
        (2, 1, None),
        (3, 2, None),
        (4, 3, None),
    ]
    for mid, rep, top in chain:
        root = resolve_root(mid, rep, top, roots)
        roots[mid] = root
        assert root == 1


def test_resolve_root_orphan():
    # Orphan reply (reply_to=999 not in known_roots -> 999)
    # Subsequent reply to this orphan inherits 999
    roots: dict[int, int] = {}
    r1 = resolve_root(msg_id=50, reply_to=999, top=None, known_roots=roots)
    assert r1 == 999
    roots[50] = r1

    r2 = resolve_root(msg_id=60, reply_to=50, top=None, known_roots=roots)
    assert r2 == 999


def test_ingest_service_set_virtual_topic_batch_local():
    # Test batch-local parent resolution in IngestService._set_virtual_topic
    mock_tg = MagicMock()
    mock_repo = MagicMock()
    service = IngestService(tg=mock_tg, repo=mock_repo)

    batch_roots: dict[int, int] = {}

    # Message 1: Top-level in batch
    m1 = make_message(id=10, reply_to_message_id=None, reply_to_top_message_id=None)
    service._set_virtual_topic(m1, batch_roots)
    assert m1.virtual_topic_id == 10
    assert batch_roots[10] == 10
    mock_repo.thread_root_of.assert_not_called()

    # Message 2: Reply to m1 in same batch (batch-local parent)
    m2 = make_message(id=11, reply_to_message_id=10, reply_to_top_message_id=None)
    service._set_virtual_topic(m2, batch_roots)
    assert m2.virtual_topic_id == 10
    assert batch_roots[11] == 10
    mock_repo.thread_root_of.assert_not_called()

    # Message 3: Reply to a parent not in batch_roots, fallback to repo.thread_root_of
    mock_repo.thread_root_of.return_value = 5
    m3 = make_message(id=20, reply_to_message_id=99, reply_to_top_message_id=None)
    service._set_virtual_topic(m3, batch_roots)
    assert m3.virtual_topic_id == 5
    assert batch_roots[20] == 5
    mock_repo.thread_root_of.assert_called_once_with(m3.chat_id, 99)
