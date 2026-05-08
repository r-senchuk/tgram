import logging
from pathlib import Path
from typing import AsyncIterator

from telethon import TelegramClient
from telethon.errors import FloodWaitError

from tgram.domain.message import Message

logger = logging.getLogger(__name__)


class TelegramClientAdapter:
    def __init__(self, api_id: int, api_hash: str, sessions_dir: Path):
        self.api_id = api_id
        self.api_hash = api_hash
        self.session_path = str(sessions_dir / "tgram")
        self._client: TelegramClient | None = None

    async def __aenter__(self) -> "TelegramClientAdapter":
        self._client = TelegramClient(self.session_path, self.api_id, self.api_hash)
        await self._client.start()
        me = await self._client.get_me()
        logger.info(f"Connected as @{me.username} ({me.first_name})")
        return self

    async def __aexit__(self, *exc) -> None:
        if self._client:
            await self._client.disconnect()

    @property
    def client(self) -> TelegramClient:
        assert self._client is not None, "Use inside `async with` block"
        return self._client

    async def iter_history(
        self,
        chat_id: int,
        *,
        min_id: int = 0,
        max_id: int = 0,
        limit: int | None = None,
    ) -> AsyncIterator[Message]:
        """Yield messages from a chat, newest first.

        min_id: only messages with id > min_id
        max_id: only messages with id < max_id
        limit:  stop after this many (None = all)
        Telethon handles FloodWait automatically; we just log when it happens.
        """
        try:
            async for tlm in self.client.iter_messages(
                chat_id, min_id=min_id, max_id=max_id, limit=limit
            ):
                if tlm is None:
                    continue
                yield self._convert(chat_id, tlm)
        except FloodWaitError as e:
            logger.warning(f"FloodWait {e.seconds}s on chat {chat_id} — Telethon will retry")
            raise

    async def get_messages_by_ids(self, chat_id: int, ids: list[int]) -> list[Message]:
        """Fetch specific message IDs (used for gap filling)."""
        result = []
        for tlm in await self.client.get_messages(chat_id, ids=ids):
            if tlm is None or getattr(tlm, "empty", False):
                continue
            result.append(self._convert(chat_id, tlm))
        return result

    async def fetch_topic_names(self, chat_id: int, topic_ids: list[int]) -> dict[int, str]:
        """Fetch MessageService objects for forum topic root IDs and return {id: title}."""
        result: dict[int, str] = {}
        CHUNK = 100
        for i in range(0, len(topic_ids), CHUNK):
            msgs = await self.client.get_messages(chat_id, ids=topic_ids[i : i + CHUNK])
            for m in msgs:
                if m is None:
                    continue
                title = getattr(getattr(m, "action", None), "title", None)
                if title:
                    result[m.id] = title
        return result

    async def list_dialogs(self) -> list[dict]:
        """Return a list of all dialogs the account has access to."""
        out = []
        async for d in self.client.iter_dialogs():
            out.append({
                "chat_id": d.id,
                "title": d.title,
                "type": (
                    "channel" if d.is_channel
                    else "group" if d.is_group
                    else "private"
                ),
                "is_forum": getattr(d.entity, "forum", False),
            })
        return out

    @staticmethod
    def _convert(chat_id: int, tlm) -> Message:
        sender = tlm.sender
        reply = tlm.reply_to

        reply_to_msg_id = getattr(reply, "reply_to_msg_id", None) if reply else None

        # In forum channels, reply_to_top_id holds the native topic root ID.
        # When a message replies directly to the topic root, Telegram omits
        # reply_to_top_id (it equals reply_to_msg_id), so we fall back to it.
        is_forum_reply = getattr(reply, "forum_topic", False) if reply else False
        if is_forum_reply:
            native_topic = getattr(reply, "reply_to_top_id", None) or reply_to_msg_id
        else:
            native_topic = None

        # Normalize empty text to None (photo-only messages send message="")
        text = tlm.message or None

        return Message(
            chat_id=chat_id,
            id=tlm.id,
            date=tlm.date,
            text=text,
            from_user_id=getattr(sender, "id", None) if sender else None,
            username=getattr(sender, "username", None) if sender else None,
            reply_to_message_id=reply_to_msg_id,
            reply_to_top_message_id=native_topic,
            virtual_topic_id=None,  # set by IngestService after save
            media_type=type(tlm.media).__name__ if tlm.media else None,
            raw_json=tlm.to_json(),
        )
