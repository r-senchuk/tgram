from pyrogram import Client
import json

# Replace these with your credentials


#CHAT_ID = "-1002096326580"  # IT Club Wroclaw (UA)
CHAT_ID = "-1001593560584"  # UA-IT in Poland (Wroclaw)
# TOPIC_ID = 2642
OUTPUT_FILE = f"{CHAT_ID}_messages.json"
BATCH_SIZE = 20 

# Create a Pyrogram Client
app = Client("sessions/m_38", api_id=API_ID, api_hash=API_HASH)

# Function to fetch and save messages from a specific topic (thread)
async def fetch_topic_messages():
    async with app:
        print(f"Fetching messages from topic {TOPIC_ID} in group {CHAT_ID}...")
        async for message in app.get_chat_history(chat_id=CHAT_ID):
            # Filter messages belonging to the specific topic
            if message.reply_to_top_message_id == TOPIC_ID:
                print(f"[{message.date}] {message.from_user.first_name}: {message.text}")
app.run(fetch_topic_messages())

async def list_groups():
    async with app:
        print("Listing all dialogs:")
        async for dialog in app.get_dialogs():
            print(f"Chat Name: {dialog.chat.title}")
            print(f"Chat ID: {dialog.chat.id}")
            print(f"Type: {dialog.chat.type}")
            print("-" * 50)

# app.run(list_groups())

#fetch all messages
async def fetch_all_messages():
    async with app:
        print(f"Fetching all messages from group {CHAT_ID}...")
        messages = [message for message in await app.get_chat_history(chat_id=CHAT_ID)]

        # Save all messages to a JSON file
        with open(OUTPUT_FILE, "w", encoding="utf-8") as file:
            json.dump([message.__dict__ for message in messages], file, ensure_ascii=False, indent=4)
        
        print(f"All messages saved to {OUTPUT_FILE}")

# app.run(fetch_all_messages())

async def fetch_last_10_messages():
    async with app:
        print(f"Fetching the last 10 messages from group {CHAT_ID}...")

        with open(OUTPUT_FILE, "w", encoding="utf-8") as file:
            async for message in app.get_chat_history(chat_id=CHAT_ID, limit=10):
                # Write each message as a JSON string
                file.write(f"{message}\n")
        
        print(f"Last 10 messages saved to {OUTPUT_FILE}")

# app.run(fetch_last_10_messages())

# BATCH_SIZE = 20

def get_last_offset():
    """
    Retrieve the last offset ID from the output file.
    If the file doesn't exist or is empty, return 0.
    """
    try:
        with open(OUTPUT_FILE, "r", encoding="utf-8") as file:
            data = [json.loads(line) for line in file]
            if data:
                return data[-1]["id"]
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    return 0


async def fetch_filtered_messages():
    async with app:
        print(f"Fetching messages from group {CHAT_ID} in batches of {BATCH_SIZE}...")

        # Start from the last offset ID
        last_offset_id = get_last_offset()
        print(f"Resuming from offset ID: {last_offset_id}")

        while True:
            filtered_messages = []
            async for message in app.get_chat_history(
                chat_id=CHAT_ID, limit=BATCH_SIZE, offset_id=last_offset_id
            ):
                # Append only the required fields, omitting 'entities'
                filtered_messages.append({
                    "_": "Message",
                    "id": message.id,
                    "from_user": {
                        "id": message.from_user.id if message.from_user else None,
                        "is_self": message.from_user.is_self if message.from_user else None,
                        "username": message.from_user.username if message.from_user else None
                    },
                    "date": message.date.strftime("%Y-%m-%dT%H:%M:%S") if message.date else None,
                    "chat": {
                        "_": "Chat",
                        "id": message.chat.id,
                        "title": message.chat.title
                    },
                    "reply_to_message_id": message.reply_to_message_id,
                    "reply_to_top_message_id": message.reply_to_top_message_id,
                    "mentioned": message.mentioned,
                    "text": message.text,
                    "media": str(message.media) if message.media else None,  # Convert media type to string
                    "web_page": {
                        "_": "WebPage",
                        "id": message.web_page.id if message.web_page else None,
                        "url": message.web_page.url if message.web_page else None,
                        "type": message.web_page.type if message.web_page else None,
                        "site_name": message.web_page.site_name if message.web_page else None,
                        "title": message.web_page.title if message.web_page else None,
                        "description": message.web_page.description if message.web_page else None
                    } if message.web_page else None,
                    "outgoing": message.outgoing
                })

            # Stop if no messages are returned
            if not filtered_messages:
                print("No more messages to fetch.")
                break

            # Append filtered messages to the output file
            with open(OUTPUT_FILE, "a", encoding="utf-8") as file:
                for msg in filtered_messages:
                    file.write(json.dumps(msg, ensure_ascii=False) + "\n")

            print(f"Fetched and stored {len(filtered_messages)} messages.")

            # Update the last offset ID
            last_offset_id = filtered_messages[-1]["id"]


# app.run(fetch_filtered_messages())