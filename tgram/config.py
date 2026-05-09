import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class Config:
    api_id: int
    api_hash: str
    default_chat_id: int | None
    batch_size: int
    data_dir: Path
    db_path: Path
    sessions_dir: Path

    @classmethod
    def load(cls) -> "Config":
        load_dotenv()
        for k in ("API_ID", "API_HASH"):
            if not os.getenv(k):
                raise RuntimeError(f"Missing required env var: {k}")
        data_dir = Path(os.getenv("OUTPUT_DIR", "./data"))
        data_dir.mkdir(parents=True, exist_ok=True)
        sessions = data_dir / "sessions"
        sessions.mkdir(parents=True, exist_ok=True)
        raw_chat_id = os.getenv("CHAT_ID")
        return cls(
            api_id=int(os.getenv("API_ID")),
            api_hash=os.getenv("API_HASH"),
            default_chat_id=int(raw_chat_id) if raw_chat_id else None,
            batch_size=int(os.getenv("BATCH_SIZE", "100")),
            data_dir=data_dir,
            db_path=data_dir / "messages.db",
            sessions_dir=sessions,
        )
