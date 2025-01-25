from abc import ABC, abstractmethod


class Storage(ABC):
    """
    Abstract base class for storage backends.
    Provides an interface for managing offsets and processed_ranges.
    """

    @abstractmethod
    def load_offsets(self):
        """
        Load offsets and processed_ranges from the storage backend.
        
        Returns:
            dict: A dictionary containing the offsets and processed_ranges.
        """
        pass

    @abstractmethod
    def save_offsets(self, offsets):
        """
        Save offsets and processed_ranges to the storage backend.
        
        Args:
            offsets (dict): The data to be saved, including processed_ranges.
        """
        pass

    @abstractmethod
    def update_processed_range(self, message_id):
        """
        Add a message ID to the processed_ranges and save the updated data.
        
        Args:
            message_id (int): The ID of the message to add to processed_ranges.
        """
        pass

    @abstractmethod
    def get_processed_ranges(self):
        """
        Retrieve all processed_ranges from the storage backend.
        
        Returns:
            list: A list of dictionaries representing processed ranges.
        """
        pass