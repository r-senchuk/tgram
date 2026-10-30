import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from tgram.adapters.db import ensure_schema, get_connection
from tgram.adapters.telegram import TelegramClientAdapter, TelegramSessionLockedError
from tgram.services.embed import EmbedService


def test_db_factory_pragmas_and_migration_gating(tmp_path: Path):
    db_file = tmp_path / "factory_test.db"

    # First call: runs migrations 1..5
    applied = ensure_schema(db_file)
    assert applied >= 5

    # Check pragmas on connection
    conn = get_connection(db_file)
    try:
        busy_timeout = conn.execute("PRAGMA busy_timeout;").fetchone()[0]
        assert busy_timeout == 10000

        journal_mode = conn.execute("PRAGMA journal_mode;").fetchone()[0]
        assert journal_mode.lower() == "wal"

        synchronous = conn.execute("PRAGMA synchronous;").fetchone()[0]
        # In SQLite, NORMAL is 1
        assert synchronous in (1, "NORMAL", "normal")

        # Verify schema_version contents
        versions = {r[0] for r in conn.execute("SELECT version FROM schema_version;").fetchall()}
        assert {1, 2, 3, 4, 5}.issubset(versions)
    finally:
        conn.close()

    # Second call: zero migrations applied (instant no-op)
    second_applied = ensure_schema(db_file)
    assert second_applied == 0


def test_db_backward_compatibility_chunk_idx(tmp_path: Path):
    db_file = tmp_path / "legacy_chunk.db"
    conn = get_connection(db_file)
    try:
        conn.execute("CREATE TABLE schema_version (version INTEGER PRIMARY KEY);")
        conn.execute("INSERT INTO schema_version (version) VALUES (1), (2), (3);")
        conn.execute(
            """CREATE TABLE embeddings (
                chat_id INTEGER,
                message_id INTEGER,
                chunk_idx INTEGER,
                vector BLOB,
                model TEXT,
                PRIMARY KEY (chat_id, message_id, chunk_idx)
            );"""
        )
        conn.commit()
    finally:
        conn.close()

    # ensure_schema should detect chunk_idx, mark 4 and 5 applied, and not run DROP TABLE
    applied = ensure_schema(db_file)
    assert applied == 0

    conn = get_connection(db_file)
    try:
        versions = {r[0] for r in conn.execute("SELECT version FROM schema_version;").fetchall()}
        assert {1, 2, 3, 4, 5}.issubset(versions)
    finally:
        conn.close()


@pytest.mark.anyio
async def test_telegram_session_file_lock(tmp_path: Path):
    sessions_dir = tmp_path / "sessions"

    with patch("tgram.adapters.telegram.TelegramClient") as mock_tg_cls:
        mock_client = MagicMock()
        mock_client.start = AsyncMock()
        mock_client.disconnect = AsyncMock()
        mock_user = MagicMock()
        mock_user.username = "testuser"
        mock_user.first_name = "Test"
        mock_client.get_me = AsyncMock(return_value=mock_user)
        mock_tg_cls.return_value = mock_client

        # Client 1 acquires lock
        adapter1 = TelegramClientAdapter(12345, "hash", sessions_dir)
        async with adapter1:
            assert (sessions_dir / "tgram.lock").exists()

            # Client 2 attempts to acquire lock concurrently -> raises TelegramSessionLockedError
            adapter2 = TelegramClientAdapter(12345, "hash", sessions_dir)
            with pytest.raises(TelegramSessionLockedError) as exc_info:
                async with adapter2:
                    pass
            assert "session lock" in str(exc_info.value)

        # After adapter1 exits, adapter3 can acquire cleanly
        adapter3 = TelegramClientAdapter(12345, "hash", sessions_dir)
        async with adapter3:
            assert adapter3._lock_file is not None


def test_embed_service_bounded_backfill(tmp_path: Path):
    mock_ollama = MagicMock()
    mock_ollama.embed.side_effect = lambda chunks: [[0.1, 0.2]] * len(chunks)

    mock_repo = MagicMock()
    # 50 missing items
    mock_repo.count_missing.return_value = 50
    # Returns 2 items per batch
    mock_repo.ids_without_embeddings.side_effect = [
        [(1, 1, "msg 1"), (1, 2, "msg 2")],
        [(1, 3, "msg 3"), (1, 4, "msg 4")],
        [(1, 5, "msg 5"), (1, 6, "msg 6")],
        [],
    ]

    svc = EmbedService(mock_ollama, mock_repo)

    # Limit to max_batches=2
    embedded = svc.backfill(batch_size=2, max_batches=2, quiet=True)
    assert embedded == 4
    assert mock_repo.save_many.call_count == 2


@pytest.mark.anyio
async def test_daemon_cycle_auto_embed(tmp_path: Path):
    from tgram.config import Config
    from tgram.interfaces.daemon import run_daemon

    test_db = tmp_path / "daemon_test.db"
    ensure_schema(test_db)

    fake_cfg = Config(
        api_id=123,
        api_hash="abc",
        default_chat_id=None,
        batch_size=100,
        data_dir=tmp_path,
        db_path=test_db,
        sessions_dir=tmp_path / "sessions",
    )

    with (
        patch("tgram.config.Config.load", return_value=fake_cfg),
        patch("tgram.interfaces.daemon.TelegramClientAdapter") as mock_tg_cls,
        patch("tgram.interfaces.daemon.IngestService") as mock_ingest_cls,
        patch("tgram.interfaces.daemon.EmbedService") as mock_embed_cls,
        patch("tgram.interfaces.daemon.OllamaAdapter") as mock_ollama_cls,
    ):
        mock_tg = MagicMock()
        mock_tg.__aenter__ = AsyncMock(return_value=mock_tg)
        mock_tg.__aexit__ = AsyncMock(return_value=None)
        mock_tg_cls.return_value = mock_tg

        mock_ingest = MagicMock()
        mock_ingest.refresh_dialogs = AsyncMock(return_value=2)
        # First call to fetch_all_new returns 5 saved messages
        mock_ingest.fetch_all_new = AsyncMock(return_value={100: 5})
        mock_ingest_cls.return_value = mock_ingest

        mock_event = asyncio.Event()
        def fake_backfill(*args, **kwargs):
            mock_event.set()
            return 5
        mock_embed = MagicMock()
        mock_embed.backfill.side_effect = fake_backfill
        mock_embed_cls.return_value = mock_embed

        with patch("asyncio.Event", return_value=mock_event):
            await run_daemon()

        assert mock_embed.backfill.called
        assert mock_embed.backfill.call_args[1]["quiet"] is True
        assert mock_embed.backfill.call_args[1]["max_batches"] == 5


@pytest.mark.anyio
async def test_daemon_recovers_when_ollama_offline(tmp_path: Path):
    from tgram.config import Config
    from tgram.interfaces.daemon import run_daemon

    test_db = tmp_path / "daemon_err_test.db"
    ensure_schema(test_db)

    fake_cfg = Config(
        api_id=123,
        api_hash="abc",
        default_chat_id=None,
        batch_size=100,
        data_dir=tmp_path,
        db_path=test_db,
        sessions_dir=tmp_path / "sessions",
    )

    with (
        patch("tgram.config.Config.load", return_value=fake_cfg),
        patch("tgram.interfaces.daemon.TelegramClientAdapter") as mock_tg_cls,
        patch("tgram.interfaces.daemon.IngestService") as mock_ingest_cls,
        patch("tgram.interfaces.daemon.EmbedService") as mock_embed_cls,
    ):
        mock_tg = MagicMock()
        mock_tg.__aenter__ = AsyncMock(return_value=mock_tg)
        mock_tg.__aexit__ = AsyncMock(return_value=None)
        mock_tg_cls.return_value = mock_tg

        mock_ingest = MagicMock()
        mock_ingest.refresh_dialogs = AsyncMock(return_value=1)
        mock_ingest.fetch_all_new = AsyncMock(return_value={100: 2})
        mock_ingest_cls.return_value = mock_ingest

        # Embedding raises ConnectionError (Ollama unreachable)
        mock_event = asyncio.Event()
        def fail_backfill(*args, **kwargs):
            mock_event.set()
            raise ConnectionError("Ollama connection refused")
        mock_embed = MagicMock()
        mock_embed.backfill.side_effect = fail_backfill
        mock_embed_cls.return_value = mock_embed

        with patch("asyncio.Event", return_value=mock_event):
            # Does not raise ConnectionError; daemon gracefully catches and logs
            await run_daemon()

        assert mock_embed.backfill.called

