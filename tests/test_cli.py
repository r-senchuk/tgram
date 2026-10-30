from datetime import datetime
from pathlib import Path
from unittest.mock import patch
import pytest

from tgram.adapters.repo_messages import MessageRepo
from tgram.config import Config
from tgram.interfaces.cli import build_parser, run
from tests.conftest import make_message


@pytest.mark.anyio
async def test_cli_repair_threads(tmp_path: Path, capsys):
    test_db = tmp_path / "cli_test.db"
    repo = MessageRepo(test_db)
    # 10 is root, 20 replies to 10
    m1 = make_message(10, chat_id=1, virtual_topic_id=10)
    m2 = make_message(20, chat_id=1, reply_to_message_id=10, virtual_topic_id=20)
    repo.save_many([m1, m2])

    fake_cfg = Config(
        api_id=123,
        api_hash="abc",
        default_chat_id=None,
        batch_size=100,
        data_dir=tmp_path,
        db_path=test_db,
        sessions_dir=tmp_path / "sessions",
    )

    parser = build_parser()

    # Dry run
    args = parser.parse_args(["repair_threads", "--dry-run"])
    with patch("tgram.config.Config.load", return_value=fake_cfg):
        ret = await run(args)
    assert ret == 0
    captured = capsys.readouterr().out
    assert "[dry-run] Would update 1 message(s)" in captured

    # Apply repair
    args = parser.parse_args(["repair_threads"])
    with patch("tgram.config.Config.load", return_value=fake_cfg):
        ret = await run(args)
    assert ret == 0
    captured = capsys.readouterr().out
    assert "Updated 1 message(s)" in captured


@pytest.mark.anyio
async def test_cli_thread_command(tmp_path: Path, capsys):
    test_db = tmp_path / "cli_test.db"
    repo = MessageRepo(test_db)
    m1 = make_message(10, chat_id=1, text="Hello root", virtual_topic_id=10, username="alice")
    m2 = make_message(20, chat_id=1, text="Reply to root", reply_to_message_id=10, virtual_topic_id=10, username="bob")
    repo.save_many([m1, m2])

    fake_cfg = Config(
        api_id=123,
        api_hash="abc",
        default_chat_id=None,
        batch_size=100,
        data_dir=tmp_path,
        db_path=test_db,
        sessions_dir=tmp_path / "sessions",
    )

    parser = build_parser()
    args = parser.parse_args(["thread", "20", "--chat", "1"])
    with patch("tgram.config.Config.load", return_value=fake_cfg):
        ret = await run(args)
    assert ret == 0
    out = capsys.readouterr().out
    assert "Conversation around msg 20" in out
    assert "[msg:10] @alice: Hello root" in out
    assert ">>>" in out
    assert "[msg:20] @bob: ↳ [reply to msg:10] Reply to root" in out


@pytest.mark.anyio
async def test_cli_status_and_gaps(tmp_path: Path, capsys):
    test_db = tmp_path / "cli_test.db"
    repo = MessageRepo(test_db)
    m1 = make_message(1, chat_id=1, virtual_topic_id=1)
    m2 = make_message(5, chat_id=1, virtual_topic_id=5)
    repo.save_many([m1, m2])

    fake_cfg = Config(
        api_id=123,
        api_hash="abc",
        default_chat_id=None,
        batch_size=100,
        data_dir=tmp_path,
        db_path=test_db,
        sessions_dir=tmp_path / "sessions",
    )

    parser = build_parser()

    # Status
    args = parser.parse_args(["status", "--chat", "1"])
    with patch("tgram.config.Config.load", return_value=fake_cfg):
        ret = await run(args)
    assert ret == 0
    out = capsys.readouterr().out
    assert "chat 1" in out
    assert "stored : 2 messages" in out
    assert "gaps   : 1" in out

    # Fetch scan
    args = parser.parse_args(["fetch_scan", "--chat", "1"])
    with patch("tgram.config.Config.load", return_value=fake_cfg):
        ret = await run(args)
    assert ret == 0
    out = capsys.readouterr().out
    assert "1 gap(s) in chat 1:" in out
    assert "2–4  (3 message(s))" in out
