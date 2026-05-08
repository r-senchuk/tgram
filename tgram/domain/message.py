from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Message:
    chat_id: int
    id: int
    date: datetime
    text: str | None
    from_user_id: int | None
    username: str | None
    reply_to_message_id: int | None
    reply_to_top_message_id: int | None  # native Telegram forum topic
    virtual_topic_id: int | None         # reply-chain root (populated by service)
    media_type: str | None
    raw_json: str                         # full Telethon JSON for future use
