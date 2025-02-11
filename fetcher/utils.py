import json
import logging
from os import getenv
from dotenv import load_dotenv

# JSON File Utilities
def load_json(file_path):
    """Load a JSON file and return the data."""
    try:
        with open(file_path, "r") as file:
            return json.load(file)
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError:
        return {}

def save_json(file_path, data):
    """Save data to a JSON file."""
    with open(file_path, "w") as file:
        json.dump(data, file, indent=4)

# Logging Utility
def setup_logger(name, log_file, level=logging.INFO):
    """Set up a logger with a specific name and file."""
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    handler = logging.FileHandler(log_file)
    handler.setFormatter(formatter)

    logger = logging.getLogger(name)
    logger.setLevel(level)
    logger.addHandler(handler)
    return logger

# ID Utilities
def is_in_range(message_id, ranges):
    """Check if a message ID falls within any processed range."""
    for range_ in ranges:
        if range_["start"] <= message_id <= range_["end"]:
            return True
    return False

def merge_ranges(ranges):
    """Merge overlapping or contiguous ranges."""
    if not ranges:
        return []
    sorted_ranges = sorted(ranges, key=lambda r: r["start"])
    merged = [sorted_ranges[0]]
    for current in sorted_ranges[1:]:
        last = merged[-1]
        if current["start"] <= last["end"] + 1:
            last["end"] = max(last["end"], current["end"])
        else:
            merged.append(current)
    return merged

# Async Utility
def is_async_iterable(obj):
    """Check if an object is an async iterable."""
    return hasattr(obj, "__aiter__")

# Environment Loader
def load_env():
    """Load environment variables from a .env file."""
    load_dotenv()