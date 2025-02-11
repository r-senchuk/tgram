import unittest
import os
import json
from pathlib import Path
from fetcher.storage_file import FileKeyValueStorage

class TestFileKeyValueStorage(unittest.TestCase):
    def setUp(self):
        """Set up a temporary file for testing."""
        self.test_file = Path("test_messages.json")
        self.storage = FileKeyValueStorage(self.test_file)

    def tearDown(self):
        """Clean up the temporary file after tests."""
        if self.test_file.exists():
            os.remove(self.test_file)

    def test_save_message(self):
        """Test saving a message."""
        message_id = 148600
        message_content = {
            "id": message_id,
            "text": "Hello, world!",
            "date": "2025-01-26T12:00:00",
            "from_user": {"id": 123456, "username": "example_user"},
            "reply_to_message_id": None
        }
        self.storage.save_message(message_id, message_content)

        # Verify that the message is saved
        with open(self.test_file, "r", encoding="utf-8") as f:
            data = json.load(f)
            self.assertIn(str(message_id), data)
            self.assertEqual(data[str(message_id)], message_content)

    def test_load_message(self):
        """Test loading a saved message."""
        message_id = 148600
        message_content = {
            "id": message_id,
            "text": "Hello, world!",
            "date": "2025-01-26T12:00:00",
            "from_user": {"id": 123456, "username": "example_user"},
            "reply_to_message_id": None
        }
        self.storage.save_message(message_id, message_content)

        # Verify that the message is loaded correctly
        loaded_message = self.storage.load_message(message_id)
        self.assertEqual(loaded_message, message_content)

    def test_load_all_messages(self):
        """Test loading all saved messages."""
        messages = {
            148600: {"id": 148600, "text": "Hello!", "date": "2025-01-26T12:00:00", "from_user": {"id": 123456}, "reply_to_message_id": None},
            148601: {"id": 148601, "text": "How are you?", "date": "2025-01-26T12:01:00", "from_user": {"id": 654321}, "reply_to_message_id": 148600}
        }

        for message_id, content in messages.items():
            self.storage.save_message(message_id, content)

        # Verify that all messages are loaded
        all_messages = self.storage.load_all_messages()
        self.assertEqual(len(all_messages), 2)
        self.assertEqual(all_messages["148600"], messages[148600])
        self.assertEqual(all_messages["148601"], messages[148601])

    def test_is_message_processed(self):
        """Test checking if a message is processed."""
        message_id = 148600
        message_content = {
            "id": message_id,
            "text": "Hello, world!",
            "date": "2025-01-26T12:00:00",
            "from_user": {"id": 123456, "username": "example_user"},
            "reply_to_message_id": None
        }
        self.storage.save_message(message_id, message_content)

        # Verify that the message is marked as processed
        self.assertTrue(self.storage.is_message_processed(148600))
        self.assertFalse(self.storage.is_message_processed(148601))

    def test_find_gaps(self):
        """Test detecting gaps in the message ID ranges."""
        messages = {
            148600: {"id": 148600, "text": "Hello!"},
            148602: {"id": 148602, "text": "How are you?"},
            148605: {"id": 148605, "text": "Goodbye!"}
        }

        for message_id, content in messages.items():
            self.storage.save_message(message_id, content)

        # Verify that gaps are detected correctly
        gaps = self.storage.find_gaps()
        self.assertEqual(gaps, [(148601, 148601), (148603, 148604)])

if __name__ == "__main__":
    unittest.main()
