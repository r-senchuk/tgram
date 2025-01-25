import json
from pathlib import Path
from .storage import Storage


class FileStorage(Storage):
    """
    File-based storage for offsets and processed_ranges.
    Stores data in a JSON file.
    """

    def __init__(self, output_dir):
        self.offset_file = Path(output_dir) / "last_offsets.json"
        self.offset_file.parent.mkdir(parents=True, exist_ok=True)  # Ensure the output directory exists

    def load_offsets(self):
        """Load processed_ranges and offsets from the file."""
        if self.offset_file.exists():
            with self.offset_file.open("r", encoding="utf-8") as file:
                return json.load(file)
        return {"processed_ranges": []}

    def save_offsets(self, offsets):
        """Save processed_ranges and offsets to the file."""
        with self.offset_file.open("w", encoding="utf-8") as file:
            json.dump(offsets, file, ensure_ascii=False, indent=4)

    def update_processed_range(self, message_id):
        """Add a message ID to processed_ranges and save."""
        offsets = self.load_offsets()
        processed_ranges = offsets.get("processed_ranges", [])
        processed_ranges.append({"start": message_id, "end": message_id})
        offsets["processed_ranges"] = self._normalize_processed_ranges(processed_ranges)
        self.save_offsets(offsets)

    def get_processed_ranges(self):
        """Retrieve all processed ranges."""
        return self.load_offsets().get("processed_ranges", [])

    def _normalize_processed_ranges(self, processed_ranges):
        """
        Normalize processed_ranges by merging overlapping or adjacent ranges.
        Ensures no duplicates or gaps between ranges.
        """
        if not processed_ranges:
            return []

        # Sort ranges by start value
        processed_ranges.sort(key=lambda r: r["start"])

        # Merge overlapping or adjacent ranges
        merged = [processed_ranges[0]]
        for current in processed_ranges[1:]:
            last = merged[-1]
            if last["end"] + 1 >= current["start"]:  # Overlap or adjacent
                last["end"] = max(last["end"], current["end"])
            else:
                merged.append(current)
        return merged