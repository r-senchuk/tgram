import asyncio
import json
from pyrogram import Client
from pyrogram.types import Message
from collections import defaultdict
from pathlib import Path

# Constants


CHAT_ID = "-1001593560584"
BATCH_SIZE = 20
OUTPUT_DIR = Path(f"{CHAT_ID}_messages_by_topic")

# Ensure output directory exists
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Create a Pyrogram Client
app = Client("sessions/m_38", api_id=API_ID, api_hash=API_HASH)

async def fetch_messages_by_topic():
    """
    Fetches all messages from a group, categorizes them by topic in batches, 
    and saves them in separate files as each batch is processed.
    """
    print(f"Fetching messages from group {CHAT_ID}...")

    topic_batches = defaultdict(list)  # Store messages in topic-wise batches

    # Fetch messages
    async for message in app.get_chat_history(chat_id=CHAT_ID, limit=0):
        # Determine the topic
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

        # If batch size is reached, save messages for the topic
        if len(topic_batches[topic_id]) >= BATCH_SIZE:
            save_messages(topic_id, topic_batches[topic_id])
            topic_batches[topic_id] = []  # Reset the batch for this topic

    # Save remaining messages in each topic
    for topic_id, messages in topic_batches.items():
        if messages:
            save_messages(topic_id, messages)

def save_messages(topic_id, messages):
    """
    Saves a batch of messages to the corresponding topic file.
    """
    file_path = OUTPUT_DIR / f"topic_{topic_id}.json"
    # Append to the file if it exists, otherwise create a new file
    if file_path.exists():
        with file_path.open("r+", encoding="utf-8") as file:
            existing_messages = json.load(file)
            existing_messages.extend(messages)
            file.seek(0)
            json.dump(existing_messages, file, ensure_ascii=False, indent=4)
    else:
        with file_path.open("w", encoding="utf-8") as file:
            json.dump(messages, file, ensure_ascii=False, indent=4)

    print(f"Saved {len(messages)} messages to {file_path}")

async def main():
    async with app:
        await fetch_messages_by_topic()

# Run the script
if __name__ == "__main__":
    asyncio.run(main())