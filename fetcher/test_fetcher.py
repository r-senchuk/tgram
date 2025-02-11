import unittest
from unittest.mock import AsyncMock, MagicMock, call, ANY
from fetcher import TelegramFetcher


class TestTelegramFetcher(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.app = AsyncMock()
        self.storage = MagicMock()
        self.chat_id = "-1001234567890"
        self.batch_size = 20
        self.fetcher = TelegramFetcher(self.app, self.storage, self.chat_id, self.batch_size)

    async def test_fetch_new(self):
        """Simplified test for fetch_new functionality."""
        # Mock get_chat_history to return an async iterable
        self.app.get_chat_history = AsyncMock()
        self.app.get_chat_history.return_value.__aiter__.return_value = [
            MagicMock(id=148650, text="Message 1"),
            MagicMock(id=148649, text="Message 2"),
        ]

        # Mock storage to simulate previously processed messages
        self.storage.is_message_processed.side_effect = lambda msg_id: msg_id == 148650

        # Run fetch_new
        await self.fetcher.fetch_new()

        # Verify that save_message is called for unprocessed messages
        self.storage.save_message.assert_called_once_with(
            148649, self.app.get_chat_history.return_value.__aiter__.return_value[1]
        )

    async def test_fetch_missed(self):
        """Simplified test for fetch_missed functionality."""
        # Mock find_gaps to return a single gap
        self.storage.find_gaps.return_value = [(148602, 148604)]

        # Mock get_chat_history to return an async iterable for the gap
        self.app.get_chat_history = AsyncMock()
        self.app.get_chat_history.return_value.__aiter__.return_value = [
            MagicMock(id=148604, text="Message Gap 3"),
            MagicMock(id=148603, text="Message Gap 2"),
            MagicMock(id=148602, text="Message Gap 1"),
        ]

        # Mock storage to simulate all messages as unprocessed
        self.storage.is_message_processed.return_value = False

        # Run fetch_missed
        await self.fetcher.fetch_missed()

        # Verify that save_message is called for each message in the gap
        class TestTelegramFetcher(unittest.IsolatedAsyncioTestCase):
            def setUp(self):
                self.app = AsyncMock()
                self.storage = MagicMock()
                self.chat_id = "-1001234567890"
                self.batch_size = 20
                self.fetcher = TelegramFetcher(self.app, self.storage, self.chat_id, self.batch_size)

            async def test_fetch_new(self):
                """Simplified test for fetch_new functionality."""
                # Mock get_chat_history to return an async iterable
                self.app.get_chat_history = AsyncMock()
                self.app.get_chat_history.return_value.__aiter__.return_value = [
                    MagicMock(id=148650, text="Message 1"),
                    MagicMock(id=148649, text="Message 2"),
                ]

                # Mock storage to simulate previously processed messages
                self.storage.is_message_processed.side_effect = lambda msg_id: msg_id == 148650

                # Run fetch_new
                await self.fetcher.fetch_new()

                # Verify that save_message is called for unprocessed messages
                self.storage.save_message.assert_called_once_with(
                    148649, self.app.get_chat_history.return_value.__aiter__.return_value[1]
                )

            async def test_fetch_missed(self):
                """Simplified test for fetch_missed functionality."""
                # Mock find_gaps to return a single gap
                self.storage.find_gaps.return_value = [(148602, 148604)]

                # Mock get_chat_history to return an async iterable for the gap
                self.app.get_chat_history = AsyncMock()
                self.app.get_chat_history.return_value.__aiter__.return_value = [
                    MagicMock(id=148604, text="Message Gap 3"),
                    MagicMock(id=148603, text="Message Gap 2"),
                    MagicMock(id=148602, text="Message Gap 1"),
                ]

                # Mock storage to simulate all messages as unprocessed
                self.storage.is_message_processed.return_value = False

                # Run fetch_missed
                await self.fetcher.fetch_missed()

                # Verify that save_message is called for each message in the gap
                self.storage.save_message.assert_has_calls([
                    call(148604, ANY),
                    call(148603, ANY),
                    call(148602, ANY),
                ], any_order=True)

            async def test_fetch_old(self):
                """Simplified test for fetch_old functionality."""
                # Mock load_all_messages to return a dictionary with message IDs
                self.storage.load_all_messages.return_value = {148600: "Message 1"}

                # Mock get_chat_history to return an async iterable
                self.app.get_chat_history = AsyncMock()
                self.app.get_chat_history.return_value.__aiter__.return_value = [
                    MagicMock(id=148599, text="Message 2"),
                    MagicMock(id=148598, text="Message 3"),
                ]

                # Mock storage to simulate all messages as unprocessed
                self.storage.is_message_processed.return_value = False

                # Run fetch_old
                await self.fetcher.fetch_old()

                # Verify that save_message is called for each message
                self.storage.save_message.assert_has_calls([
                    call(148599, ANY),
                    call(148598, ANY),
                ], any_order=True)

            async def test_list_channels(self):
                """Simplified test for list_channels functionality."""
                # Mock get_dialogs to return an async iterable
                self.app.get_dialogs = AsyncMock()
                self.app.get_dialogs.return_value.__aiter__.return_value = [
                    MagicMock(chat=MagicMock(id=12345, title="Channel 1", type="channel")),
                    MagicMock(chat=MagicMock(id=67890, title="Supergroup 1", type="supergroup")),
                ]

                # Run list_channels
                await self.fetcher.list_channels()

                # Verify that the channels are listed (print statements)
                self.app.get_dialogs.assert_called_once()


        if __name__ == "__main__":
            unittest.main()