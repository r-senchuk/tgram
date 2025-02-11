from abc import ABC, abstractmethod


class KeyValueStorage(ABC):
    """
    Abstract interface for key-value storage.
    Handles message saving, loading, and checking processed status.
    """

    @abstractmethod
    def save_message(self, message_id, message_content):
        """Save a single raw message."""
        pass

    @abstractmethod
    def load_message(self, message_id):
        """Load a single message by ID."""
        pass

    @abstractmethod
    def load_all_messages(self):
        """Load all stored messages."""
        pass

    @abstractmethod
    def is_message_processed(self, message_id):
        """Check if a message ID has already been processed."""
        pass

    @abstractmethod
    def find_gaps(self):
        """
        Identify gaps in the stored message ID ranges.
        
        Returns:
            list[tuple[int, int]]: A list of (start, end) tuples representing missing ranges.
        """
        pass