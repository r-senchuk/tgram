from contextlib import contextmanager
from datetime import datetime
import sqlite3
from unittest.mock import MagicMock
import pytest

from tgram.adapters.repo_embeddings import EmbeddingRepo
from tgram.adapters.repo_messages import MessageRepo
from tgram.adapters.search_fts import ContextMessage, FTSSearch, SearchHit, _clean_fts_query
from tgram.services.ai import AIService
from tgram.services.search import SearchService, has_fts_operators
from tests.conftest import make_message


# 1. _clean_fts_query sanitizer cases
def test_clean_fts_query_punctuation():
    # Punctuation / special chars ( ) + - ^ : should be stripped/replaced by spaces
    q = "(python) + (sql) - bad ^ text : ok"
    assert _clean_fts_query(q) == "python sql bad text ok"


def test_clean_fts_query_unbalanced_quotes():
    # Unbalanced quotes are stripped
    assert _clean_fts_query('hello "world') == "hello world"
    # Balanced quotes are preserved for phrase search
    assert _clean_fts_query('"exact phrase"') == '"exact phrase"'


def test_clean_fts_query_bare_boolean_operators():
    # Single bare boolean operators return empty query '""'
    assert _clean_fts_query("AND") == '""'
    assert _clean_fts_query("OR") == '""'
    assert _clean_fts_query("NOT") == '""'
    assert _clean_fts_query("NEAR") == '""'

    # Bare boolean operators in multi-word queries are lowercased so FTS5 doesn't treat them as syntax operators
    assert _clean_fts_query("not working") == "not working"
    assert _clean_fts_query("near station") == "near station"
    assert _clean_fts_query("apple AND orange") == "apple and orange"


def test_clean_fts_query_match_any():
    # match_any=True extracts content words (>= 4 chars) and joins with OR
    assert _clean_fts_query("what is the weather today", match_any=True) == "what OR weather OR today"
    # Fallback to all words if all are < 4 chars
    assert _clean_fts_query("cat dog pig", match_any=True) == "cat OR dog OR pig"
    # Empty tokens return '""'
    assert _clean_fts_query("", match_any=True) == '""'


# 2. has_fts_operators
def test_has_fts_operators():
    assert has_fts_operators('"exact phrase"') is True
    assert has_fts_operators(" Document*") is True
    assert has_fts_operators("test*") is True
    assert has_fts_operators("normal queries") is False
    assert has_fts_operators("hello world") is False


# 3. FTSSearch.search graceful handling of OperationalError
def test_fts_search_operational_error_graceful(message_repo: MessageRepo, embedding_repo: EmbeddingRepo, fts_search: FTSSearch):
    # Insert a message and an embedding
    m1 = make_message(id=1, text="vector fallback message", virtual_topic_id=1)
    message_repo.save(m1)
    embedding_repo.save_many([(1, 1, 0, [1.0, 0.0], "test-model")])

    orig_conn = fts_search._conn

    class ConnectionProxy:
        def __init__(self, conn):
            self._conn = conn

        def __getattr__(self, name):
            return getattr(self._conn, name)

        def execute(self, sql, *args, **kwargs):
            if "messages_fts MATCH" in sql:
                raise sqlite3.OperationalError("fts5: simulated syntax error")
            return self._conn.execute(sql, *args, **kwargs)

    @contextmanager
    def failing_conn():
        with orig_conn() as c:
            yield ConnectionProxy(c)

    fts_search._conn = failing_conn

    # Without vector: returns empty list, does not crash
    hits = fts_search.search("bad query")
    assert hits == []

    # With vector: falls back to vector hits from embedding_repo
    hits_vec = fts_search.search("bad query", query_vector=[1.0, 0.0])
    assert len(hits_vec) == 1
    assert hits_vec[0].message_id == 1


# 4. SearchService.search mode reporting
def test_search_service_mode_reporting(fts_search: FTSSearch):
    mock_embedder = MagicMock()
    mock_embedder.embed.return_value = [[0.1, 0.2]]

    # 1. semantic=False -> "fts"
    svc = SearchService(fts=fts_search, embedder=mock_embedder)
    _, mode = svc.search("hello", semantic=False)
    assert mode == "fts"

    # 2. embedder=None -> "fts"
    svc_no_emb = SearchService(fts=fts_search, embedder=None)
    _, mode = svc_no_emb.search("hello")
    assert mode == "fts"

    # 3. fts.embedding_repo=None -> "fts"
    fts_no_repo = FTSSearch(fts_search.db_path, embedding_repo=None)
    svc_no_repo = SearchService(fts=fts_no_repo, embedder=mock_embedder)
    _, mode = svc_no_repo.search("hello")
    assert mode == "fts"

    # 4. Operators -> "fts (operators)"
    _, mode = svc.search('"exact phrase"')
    assert mode == "fts (operators)"
    _, mode = svc.search(" Document*")
    assert mode == "fts (operators)"

    # 5. Hybrid -> "hybrid"
    _, mode = svc.search("regular query")
    assert mode == "hybrid"

    # 6. Embedder fails -> "fts (ollama unreachable)"
    failing_embedder = MagicMock()
    failing_embedder.embed.side_effect = RuntimeError("Ollama connection failed")
    svc_failing = SearchService(fts=fts_search, embedder=failing_embedder)
    _, mode = svc_failing.search("regular query")
    assert mode == "fts (ollama unreachable)"


# 5. EmbeddingRepo.search_similar with filters
try:
    import sqlite_vec
    SQLITE_VEC_AVAILABLE = True
except Exception:
    SQLITE_VEC_AVAILABLE = False


@pytest.mark.skipif(not SQLITE_VEC_AVAILABLE, reason="sqlite-vec not available")
def test_embedding_repo_search_similar_filters(message_repo: MessageRepo, embedding_repo: EmbeddingRepo):
    # Insert messages with different chats, topics, and dates
    m1 = make_message(id=1, chat_id=1, reply_to_top_message_id=10, date=datetime(2026, 1, 1), text="msg 1")
    m2 = make_message(id=2, chat_id=1, reply_to_top_message_id=20, date=datetime(2026, 2, 1), text="msg 2")
    m3 = make_message(id=3, chat_id=2, reply_to_top_message_id=10, date=datetime(2026, 3, 1), text="msg 3")
    message_repo.save_many([m1, m2, m3])

    # Save embeddings
    embedding_repo.save_many([
        (1, 1, 0, [1.0, 0.0], "test-model"),
        (1, 2, 0, [0.0, 1.0], "test-model"),
        (2, 3, 0, [0.7, 0.7], "test-model"),
    ])

    # Filter chat_id:
    res_chat = embedding_repo.search_similar([1.0, 0.0], chat_id=1)
    assert all(r[0] == 1 for r in res_chat)
    assert {r[1] for r in res_chat} == {1, 2}

    # Filter topic_id:
    res_topic = embedding_repo.search_similar([1.0, 0.0], topic_id=10)
    msg_ids_topic = {r[1] for r in res_topic}
    assert 1 in msg_ids_topic
    assert 3 in msg_ids_topic
    assert 2 not in msg_ids_topic

    # Filter since:
    res_since = embedding_repo.search_similar([1.0, 0.0], since="2026-01-15")
    msg_ids_since = {r[1] for r in res_since}
    assert 1 not in msg_ids_since
    assert 2 in msg_ids_since
    assert 3 in msg_ids_since

    # Filter until:
    res_until = embedding_repo.search_similar([1.0, 0.0], until="2026-01-15")
    msg_ids_until = {r[1] for r in res_until}
    assert msg_ids_until == {1}


# 6. AIService._build_context
def test_ai_service_build_context():
    mock_fts = MagicMock()
    mock_llm = MagicMock()
    mock_llm.context_chars = 10_000

    ai_service = AIService(fts=mock_fts, llm=mock_llm)

    # 3 hits: hit1 and hit2 share (chat_id=1, virtual_topic_id=10); hit3 is (chat_id=1, virtual_topic_id=20)
    hit1 = SearchHit(chat_id=1, message_id=10, date="2026-01-01T12:00:00", text="hit 1", username="alice", from_user_id=1, topic_id=None, topic_title="General", snippet="hit 1", virtual_topic_id=10)
    hit2 = SearchHit(chat_id=1, message_id=11, date="2026-01-01T12:05:00", text="hit 2", username="alice", from_user_id=1, topic_id=None, topic_title="General", snippet="hit 2", virtual_topic_id=10)
    hit3 = SearchHit(chat_id=1, message_id=20, date="2026-01-01T13:00:00", text="hit 3", username="bob", from_user_id=2, topic_id=None, topic_title="General", snippet="hit 3", virtual_topic_id=20)

    def mock_get_conv(hit, **kwargs):
        if hit.virtual_topic_id == 10:
            return [
                ContextMessage(message_id=10, date="2026-01-01T12:00:00", text="hit 1", username="alice", from_user_id=1, is_hit=True, chat_id=1),
                ContextMessage(message_id=11, date="2026-01-01T12:05:00", text="hit 2", username="alice", from_user_id=1, is_hit=False, chat_id=1, reply_to_message_id=10),
            ]
        else:
            return [
                ContextMessage(message_id=20, date="2026-01-01T13:00:00", text="hit 3", username="bob", from_user_id=2, is_hit=True, chat_id=1),
            ]

    mock_fts.get_conversation.side_effect = mock_get_conv

    # Run _build_context
    context, context_index = ai_service._build_context([hit1, hit2, hit3])

    # Thread deduplication: get_conversation is called only twice (for thread 10 and thread 20)
    assert mock_fts.get_conversation.call_count == 2

    # Context index return value: maps msg_id -> (chat_id, msg_id)
    assert context_index[10] == (1, 10)
    assert context_index[11] == (1, 11)
    assert context_index[20] == (1, 20)

    # Budget enforcement
    mock_llm.context_chars = 120
    small_context, small_index = ai_service._build_context([hit1, hit2, hit3])
    assert len(small_context) <= 120
    assert 20 not in small_index
