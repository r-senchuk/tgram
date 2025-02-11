import json
from pathlib import Path


class FileKeyValueStorage:
    """
    A file-based implementation of the KeyValueStorage abstraction.
    Stores messages as key-value pairs in a JSON file.
    """

    def __init__(self, file_path):
        self.file_path = Path(file_path)
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.file_path.exists():
            with self.file_path.open("w", encoding="utf-8") as f:
                json.dump({}, f)

    def _load_data(self):
        """Load all data from the storage file."""
        with self.file_path.open("r", encoding="utf-8") as f:
            return json.load(f)

    def _save_data(self, data):
        """Save all data to the storage file."""
        with self.file_path.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)

    def save_message(self, message_id, message_content):
        """
        Save a single raw message to storage.
        Args:
            message_id (int): The unique message ID.
            message_content (dict): The raw message content.
        """
        data = self._load_data()
        data[str(message_id)] = message_content
        self._save_data(data)

    def load_message(self, message_id):
        """
        Load a single message by ID.
        Args:
            message_id (int): The unique message ID.
        Returns:
            dict or None: The raw message content, or None if not found.
        """
        data = self._load_data()
        return data.get(str(message_id))

    def load_all_messages(self):
        """
        Load all stored messages.
        Returns:
            dict: All stored messages, excluding non-message metadata.
        """
        data = self._load_data()
        return {k: v for k, v in data.items() if k.isdigit()}

    def is_message_processed(self, message_id):
        """
        Check if a message ID has already been processed.
        Args:
            message_id (int): The unique message ID.
        Returns:
            bool: True if the message is already processed, False otherwise.
        """
        data = self._load_data()
        return str(message_id) in data

    def find_gaps(self):
        """
        Identify missing message ID ranges in the storage.
        Returns:
            list[tuple[int, int]]: A list of (start, end) tuples representing missing ranges.
        """
        all_ids = sorted(int(k) for k in self._load_data().keys() if k.isdigit())
        gaps = []
        for i in range(1, len(all_ids)):
            if all_ids[i] > all_ids[i - 1] + 1:
                gaps.append((all_ids[i - 1] + 1, all_ids[i] - 1))
        return gaps