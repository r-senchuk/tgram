from dataclasses import dataclass


@dataclass(frozen=True)
class Topic:
    chat_id: int
    topic_id: int
    title: str
