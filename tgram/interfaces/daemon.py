import asyncio
import logging
import os
import signal
import time

from tgram.adapters.repo_channels import ChannelRepo
from tgram.adapters.repo_messages import MessageRepo
from tgram.adapters.repo_topics import TopicRepo
from tgram.adapters.telegram import TelegramClientAdapter
from tgram.config import Config
from tgram.services.ingest import IngestService

logger = logging.getLogger(__name__)


async def run_daemon() -> None:
    cfg = Config.load()
    fetch_interval  = int(os.getenv("FETCH_INTERVAL_MINUTES",   "5"))  * 60
    refresh_interval = int(os.getenv("REFRESH_DIALOGS_MINUTES", "60")) * 60

    repo_msg    = MessageRepo(cfg.db_path)
    repo_chan   = ChannelRepo(cfg.db_path)
    repo_topics = TopicRepo(cfg.db_path)

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)

    async with TelegramClientAdapter(cfg.api_id, cfg.api_hash, cfg.sessions_dir) as tg:
        svc = IngestService(tg, repo_msg)

        # Sync dialogs once on startup
        n = await svc.refresh_dialogs(repo_chan)
        logger.info(f"Daemon started — {n} dialogs synced. "
                    f"Fetch every {fetch_interval//60}m, refresh every {refresh_interval//60}m. "
                    f"Ctrl+C to stop.")

        last_fetch   = 0.0
        last_refresh = time.monotonic()  # already refreshed above

        while not stop.is_set():
            now = time.monotonic()

            if now - last_refresh >= refresh_interval:
                try:
                    await svc.refresh_dialogs(repo_chan)
                except Exception as e:
                    logger.exception(f"Dialog refresh failed: {e}")
                last_refresh = time.monotonic()

            if now - last_fetch >= fetch_interval:
                try:
                    results = await svc.fetch_all_new(repo_chan, repo_topics)
                    total = sum(n for n in results.values() if n > 0)
                    if total:
                        logger.info(f"Cycle done: {total} new messages")
                except Exception as e:
                    logger.exception(f"fetch_all_new failed: {e}")
                last_fetch = time.monotonic()

            # Sleep in short increments so stop signal is responsive
            try:
                await asyncio.wait_for(stop.wait(), timeout=10)
            except asyncio.TimeoutError:
                pass

    logger.info("Daemon stopped.")
