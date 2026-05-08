import logging

from tgram.adapters.repo_channels import ChannelRepo
from tgram.adapters.repo_messages import MessageRepo
from tgram.adapters.repo_topics import TopicRepo
from tgram.adapters.telegram import TelegramClientAdapter
from tgram.domain.channel import Channel
from tgram.domain.message import Message
from tgram.domain.topic import Topic

logger = logging.getLogger(__name__)


BATCH_SIZE = 500  # messages per SQLite transaction


class IngestService:
    def __init__(self, tg: TelegramClientAdapter, repo: MessageRepo):
        self.tg = tg
        self.repo = repo

    async def fetch_new(self, chat_id: int) -> int:
        """Fetch messages newer than the highest stored ID. Returns count saved."""
        since = self.repo.max_id(chat_id) or 0
        logger.info(f"fetch_new chat={chat_id} since_id={since}")
        return await self._stream_and_save(
            self.tg.iter_history(chat_id, min_id=since), chat_id
        )

    async def fetch_old(self, chat_id: int, limit: int | None = None) -> int:
        """Fetch one batch of messages older than the lowest stored ID."""
        oldest = self.repo.min_id(chat_id) or 0
        logger.info(f"fetch_old chat={chat_id} before_id={oldest}")
        return await self._stream_and_save(
            self.tg.iter_history(chat_id, max_id=oldest, limit=limit), chat_id
        )

    async def fetch_old_loop(self, chat_id: int) -> int:
        """Keep fetching older messages until the channel beginning is reached."""
        total = 0
        while True:
            n = await self.fetch_old(chat_id)
            total += n
            if n == 0:
                logger.info(f"fetch_old_loop done — {total} total messages saved")
                break
        return total

    async def fetch_gap(self, chat_id: int, start_id: int, end_id: int) -> int:
        """Fetch a specific ID range (e.g. a gap found by fetch_scan)."""
        if start_id > end_id:
            raise ValueError("start_id must be <= end_id")
        logger.info(f"fetch_gap chat={chat_id} range={start_id}-{end_id}")
        saved = 0
        CHUNK = 100  # Telethon limit for get_messages with id list
        for chunk_start in range(start_id, end_id + 1, CHUNK):
            ids = list(range(chunk_start, min(chunk_start + CHUNK, end_id + 1)))
            msgs = []
            for msg in await self.tg.get_messages_by_ids(chat_id, ids):
                if self.repo.exists(chat_id, msg.id):
                    continue
                self._set_virtual_topic(msg)
                msgs.append(msg)
            if msgs:
                self.repo.save_many(msgs)
                saved += len(msgs)
        return saved

    async def _stream_and_save(self, stream, chat_id: int) -> int:
        """Consume an async message stream, batching writes every BATCH_SIZE messages."""
        saved = 0
        batch: list[Message] = []
        async for msg in stream:
            if self.repo.exists(chat_id, msg.id):
                continue
            self._set_virtual_topic(msg)
            batch.append(msg)
            if len(batch) >= BATCH_SIZE:
                self.repo.save_many(batch)
                saved += len(batch)
                logger.info(f"  saved {saved} so far…")
                batch = []
        if batch:
            self.repo.save_many(batch)
            saved += len(batch)
        return saved

    async def refresh_dialogs(self, repo_channels: ChannelRepo) -> int:
        """Sync channels table from Telegram dialogs. New channels default to enabled=False."""
        dialogs = await self.tg.list_dialogs()
        for d in dialogs:
            repo_channels.upsert(Channel(
                chat_id=d["chat_id"], title=d["title"],
                type=d["type"], is_forum=d["is_forum"],
                last_fetched_id=None, oldest_fetched_id=None,
                last_fetch_at=None, enabled=False,
            ))
        logger.info(f"refresh_dialogs: synced {len(dialogs)} dialog(s)")
        return len(dialogs)

    async def fetch_all_new(self, repo_channels: ChannelRepo,
                            repo_topics: TopicRepo) -> dict[int, int]:
        """Fetch new messages for every enabled channel. Returns {chat_id: count_saved}."""
        channels = repo_channels.list_enabled()
        if not channels:
            logger.info("fetch_all_new: no enabled channels")
            return {}
        results: dict[int, int] = {}
        for ch in channels:
            try:
                n = await self.fetch_new(ch.chat_id)
                if n > 0:
                    max_id = self.repo.max_id(ch.chat_id)
                    repo_channels.update_last_fetched(ch.chat_id, max_id)
                    await self.sync_topics(ch.chat_id, repo_topics)
                results[ch.chat_id] = n
            except Exception as e:
                logger.exception(f"fetch_all_new: failed for chat {ch.chat_id}: {e}")
                results[ch.chat_id] = -1
        total = sum(n for n in results.values() if n > 0)
        failed = sum(1 for n in results.values() if n < 0)
        logger.info(f"fetch_all_new done: {total} messages across {len(channels)} channels, {failed} failed")
        return results

    async def sync_topics(self, chat_id: int, repo_topics: TopicRepo) -> int:
        """Fetch names for topic IDs seen in messages but not yet in the topics table."""
        unknown = repo_topics.unknown_topic_ids(chat_id)
        if not unknown:
            return 0
        logger.info(f"sync_topics: resolving {len(unknown)} unknown topic id(s) for chat {chat_id}")
        names = await self.tg.fetch_topic_names(chat_id, unknown)
        for topic_id, title in names.items():
            repo_topics.save(Topic(chat_id=chat_id, topic_id=topic_id, title=title))
        return len(names)

    def _set_virtual_topic(self, msg: Message) -> None:
        """Resolve and stamp virtual_topic_id on the (frozen) message in-place."""
        if msg.reply_to_message_id:
            root = self.repo.reply_root(msg.chat_id, msg.reply_to_message_id)
        else:
            root = msg.id
        object.__setattr__(msg, "virtual_topic_id", root)
