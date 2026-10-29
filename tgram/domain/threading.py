from typing import Mapping


def is_thread_start(reply_to: int | None, top: int | None) -> bool:
    return reply_to is None or reply_to == top


def resolve_root(
    msg_id: int,
    reply_to: int | None,
    top: int | None,
    known_roots: Mapping[int, int],
) -> int:
    if is_thread_start(reply_to, top):
        return msg_id
    return known_roots.get(reply_to, reply_to)  # orphan -> missing parent's id
