from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Channel:
    chat_id: int
    title: str | None
    type: str                  # "channel" | "supergroup" | "group" | "private"
    is_forum: bool
    last_fetched_id: int | None
    oldest_fetched_id: int | None
    last_fetch_at: datetime | None
    enabled: bool
