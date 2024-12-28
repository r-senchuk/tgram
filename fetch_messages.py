import json
import os
from pathlib import Path
from dotenv import load_dotenv
from collections import defaultdict
from pyrogram import Client
import signal
import sys

# Constants
load_dotenv()
# Constants from .env
API_ID = os.getenv("API_ID")
API_HASH = os.getenv("API_HASH")
CHAT_ID = os.getenv("CHAT_ID")
BATCH_SIZE = int(os.getenv("BATCH_SIZE", 20))
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", f"{CHAT_ID}_messages_by_topic"))

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

OFFSET_FILE = OUTPUT_DIR / "last_offsets.json"

def load_offsets():
    """Load processed_ranges from the file."""
    if OFFSET_FILE.exists():
        with OFFSET_FILE.open("r", encoding="utf-8") as file:
            try:
                return json.load(file)
            except json.JSONDecodeError:
                pass
    return {"processed_ranges": []}


def save_offsets(offsets):
    """Save processed_ranges to the file."""
    with OFFSET_FILE.open("w", encoding="utf-8") as file:
        json.dump(offsets, file, ensure_ascii=False, indent=4)


def is_message_processed(message_id, processed_ranges):
    """Check if a message ID is already processed."""
    for r in processed_ranges:
        if r["start"] <= message_id <= r["end"]:
            return True
    return False


def normalize_processed_ranges(processed_ranges):
    """Normalize processed_ranges by merging overlapping or adjacent ranges."""
    if not processed_ranges:
        return []

    # Sort ranges by start
    processed_ranges.sort(key=lambda r: r["start"])

    # Merge ranges
    merged = [processed_ranges[0]]
    for current in processed_ranges[1:]:
        last = merged[-1]
        if last["end"] + 1 >= current["start"]:  # Overlapping or adjacent ranges
            last["end"] = max(last["end"], current["end"])
        else:
            merged.append(current)

    return merged


def update_processed_range(offsets, message_id):
    """Add a message ID to processed_ranges and normalize ranges."""
    processed_ranges = offsets.get("processed_ranges", [])

    # Add the new range
    processed_ranges.append({"start": message_id, "end": message_id})

    # Normalize ranges
    offsets["processed_ranges"] = normalize_processed_ranges(processed_ranges)
    save_offsets(offsets)


def save_messages(topic_id, messages, prepend=False):
    """Save a batch of messages to the corresponding topic file."""
    file_path = OUTPUT_DIR / f"topic_{topic_id}.json"
    if file_path.exists():
        with file_path.open("r+", encoding="utf-8") as file:
            existing_messages = json.load(file)
            if prepend:
                messages.extend(existing_messages)
            else:
                existing_messages.extend(messages)
            file.seek(0)
            json.dump(existing_messages, file, ensure_ascii=False, indent=4)
    else:
        with file_path.open("w", encoding="utf-8") as file:
            json.dump(messages, file, ensure_ascii=False, indent=4)


async def fetch_messages(app, direction="newest"):
    """Fetch messages in the specified direction ('newest' or 'oldest')."""
    offsets = load_offsets()
    processed_ranges = offsets.get("processed_ranges", [])

    print(f"Fetching messages in {direction} direction.")
    last_offset_id = None  # Start without an offset
    while True:
        fetch_kwargs = {"chat_id": CHAT_ID, "limit": BATCH_SIZE}
        if last_offset_id:
            fetch_kwargs["offset_id"] = last_offset_id

        topic_batches = defaultdict(list)
        messages_fetched = 0
        boundary_message_id = None  # Track the boundary message ID for the current batch

        async for message in app.get_chat_history(**fetch_kwargs):
            # Debug: Log the fetched message ID
            print(f"Fetched message ID: {message.id}")

            # Skip messages already processed
            if is_message_processed(message.id, processed_ranges):
                print(f"Skipping already processed message ID: {message.id}")
                continue

            # Process the message
            topic_id = message.reply_to_top_message_id or "general"
            topic_batches[topic_id].append({
                "id": message.id,
                "from_user": {
                    "id": message.from_user.id if message.from_user else None,
                    "username": message.from_user.username if message.from_user else None
                },
                "date": message.date.strftime("%Y-%m-%dT%H:%M:%S") if message.date else None,
                "text": message.text,
                "media": str(message.media) if message.media else None,
                "reply_to_message_id": message.reply_to_message_id
            })

            # Update ranges and track the boundary message ID
            if boundary_message_id is None:
                boundary_message_id = message.id
            elif direction == "newest":
                boundary_message_id = max(boundary_message_id, message.id)
            elif direction == "oldest":
                boundary_message_id = min(boundary_message_id, message.id)

            update_processed_range(offsets, message.id)
            messages_fetched += 1

        # Debug: Log processed_ranges after the batch
        print(f"Processed ranges after batch: {processed_ranges}")

        # Exit if no new messages were fetched
        if messages_fetched == 0:
            print(f"No more {direction} messages to fetch. Stopping.")
            break

        # Update the offset for the next iteration
        last_offset_id = boundary_message_id

        # Save messages in batches
        for topic_id, messages in topic_batches.items():
            save_messages(topic_id, messages, prepend=(direction == "oldest"))


async def fetch_newest_messages(app):
    """Fetch newest messages."""
    await fetch_messages(app, direction="newest")


async def fetch_oldest_messages(app):
    """Fetch oldest messages."""
    await fetch_messages(app, direction="oldest")


async def main():
    """Main function to start the client and run fetch functions."""
    async with Client("sessions/m_38", api_id=API_ID, api_hash=API_HASH) as app:
        # Uncomment the desired function to fetch messages
        await fetch_oldest_messages(app)
        # await fetch_newest_messages(app)


def handle_exit(signum, frame):
    """Handle script termination gracefully."""
    print("\nGracefully stopping...")
    sys.exit(0)


if __name__ == "__main__":
    import asyncio
    signal.signal(signal.SIGINT, handle_exit)  # Handle Ctrl+C
    signal.signal(signal.SIGTERM, handle_exit)  # Handle termination signals
    asyncio.run(main())