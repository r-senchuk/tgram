from abc import ABC, abstractmethod
from collections import defaultdict


class Fetcher(ABC):
    """
    Abstract base class for fetching messages from Telegram.
    Provides methods to fetch new, old, and missed messages, and list available channels.
    """

    @abstractmethod
    async def fetch_new(self):
        """Fetch the newest messages."""
        pass

    @abstractmethod
    async def fetch_old(self):
        """Fetch the oldest messages."""
        pass

    @abstractmethod
    async def fetch_scan(self):
        """Fetch missed messages (gaps)."""
        pass

    @abstractmethod
    async def list_channels(self):
        """List available channels accessible by the client."""
        pass


class TelegramFetcher(Fetcher):
    """
    Implementation of the Fetcher abstraction for Telegram using Pyrogram.
    """

    def __init__(self, app, storage, chat_id, batch_size):
        self.app = app  # Pyrogram client instance
        self.storage = storage  # KeyValueStorage instance
        self.chat_id = chat_id  # Target chat/channel ID
        self.batch_size = batch_size  # Number of messages per batch

    async def fetch_new(self):
        """Fetch the newest messages and store them."""
        print(f"Starting to fetch newest messages for chat {self.chat_id}...")
        fetch_kwargs = {"chat_id": self.chat_id, "limit": self.batch_size}

        while True:
            messages_fetched = 0

            try:
                async for message in self._fetch_messages(fetch_kwargs):
                    if self.storage.is_message_processed(message.id):
                        print("Stopping fetch: already processed message reached.")
                        return

                    self._process_message(message)
                    messages_fetched += 1

            except Exception as e:
                print(f"Error fetching newest messages: {e}")
                break

            if messages_fetched == 0:
                print("No new messages found. Stopping fetch.")
                break

            print(f"Fetched {messages_fetched} messages. Continuing...")

    async def fetch_old(self):
        """Fetch the oldest messages and store them."""
        print(f"Starting to fetch oldest messages for chat {self.chat_id}...")
        last_stored_message = min(
            map(int, self.storage.load_all_messages().keys()), default=None
        )
        fetch_kwargs = {"chat_id": self.chat_id, "limit": self.batch_size}

        if last_stored_message is not None:
            fetch_kwargs["offset_id"] = last_stored_message - 1

        while True:
            messages_fetched = 0

            try:
                async for message in self._fetch_messages(fetch_kwargs):
                    if self.storage.is_message_processed(message.id):
                        continue

                    self._process_message(message)
                    messages_fetched += 1

            except Exception as e:
                print(f"Error fetching oldest messages: {e}")
                break

            if messages_fetched == 0:
                print("No more old messages. Stopping fetch.")
                break

            print(f"Fetched {messages_fetched} messages. Continuing...")

    async def fetch_scan(self):
        print("Scanning for missing messages...")
        # Mock: Generate a list of missing message ranges
        missing_ranges = [(100, 120), (250, 270)]
        print("Missing message ranges:", missing_ranges)
        return missing_ranges
    
    async def fetch_gap(self, start_id, end_id):
        print(f"Fetching messages from {start_id} to {end_id}...")
        for message_id in range(start_id, end_id + 1):
            print(f"Fetched message {message_id}")
        print("Gap fetch completed.")

    async def list_channels(self):
        """List available channels the client can access."""
        print("Fetching available channels...")

        try:
            async for dialog in self.app.get_dialogs():
                if dialog.chat.type in ["channel", "supergroup"]:
                    print(f"{dialog.chat.title} ({dialog.chat.id})")
        except Exception as e:
            print(f"Error listing channels: {e}")

    async def _fetch_messages(self, fetch_kwargs):
        """Helper to fetch messages for better testability."""
        async for message in self.app.get_chat_history(**fetch_kwargs):
            yield message

    def _process_message(self, message):
        """Process and store a single message."""
        message_data = {
            "id": message.id,
            "from_user": {
                "id": message.from_user.id if message.from_user else None,
                "username": message.from_user.username if message.from_user else None
            },
            "date": message.date.strftime("%Y-%m-%dT%H:%M:%S") if message.date else None,
            "text": message.text,
            "media": str(message.media) if message.media else None,
            "reply_to_message_id": message.reply_to_message_id
        }
        self.storage.save_message(message.id, message_data)