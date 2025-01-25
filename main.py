import asyncio
from pyrogram import Client
from config import load_config
from fetcher.fetcher import list_channels
from fetcher.storage_file import FileStorage

# Global state
ACTIVE_CHANNEL = None  # Keeps track of the active channel

def use_channel(channel_id):
    """Set the active channel for fetching messages."""
    global ACTIVE_CHANNEL
    ACTIVE_CHANNEL = channel_id
    print(f"Active channel set to: {channel_id}")


def join_channel(app, invite_link_or_id):
    """Join a new channel using an invite link or ID."""
    print(f"Mock: Joining channel with {invite_link_or_id}...")
    print("Successfully joined the channel!")


async def fetch_new(app, storage, config):
    """Fetch the newest messages from the active channel."""
    if not ACTIVE_CHANNEL:
        print("Error: No active channel selected. Use the 'use' command to select one.")
        return
    config["CHAT_ID"] = ACTIVE_CHANNEL
    await fetch_newest_messages(app, storage, config)


async def fetch_old(app, storage, config):
    """Fetch the oldest messages from the active channel."""
    if not ACTIVE_CHANNEL:
        print("Error: No active channel selected. Use the 'use' command to select one.")
        return
    config["CHAT_ID"] = ACTIVE_CHANNEL
    await fetch_oldest_messages(app, storage, config)


def segregate_messages(storage):
    """Segregate fetched messages into topic-based files."""
    print("Mock: Segregating fetched messages by topic...")
    # Logic for segregation would go here


def simplify_messages(storage):
    """Simplify fetched messages by retaining only necessary fields."""
    print("Mock: Simplifying fetched messages...")
    # Logic for simplifying would go here


def main():
    """Main entry point for the application."""
    try:
        # Load configuration
        config = load_config()

        # Initialize storage
        storage = FileStorage(config["OUTPUT_DIR"])

        # Initialize Pyrogram client
        app = Client("sessions/m_38", api_id=config["API_ID"], api_hash=config["API_HASH"])

        # Command loop
        while True:
            command = input("Enter a command (list/use/join/fetch/segregate/simplify/exit): ").strip()
            if command == "list":
                list_channels(app)
            elif command.startswith("use"):
                _, channel_id = command.split(maxsplit=1)
                use_channel(channel_id)
            elif command.startswith("join"):
                _, invite_link_or_id = command.split(maxsplit=1)
                join_channel(app, invite_link_or_id)
            elif command == "fetch new":
                asyncio.run(fetch_new(app, storage, config))
            elif command == "fetch old":
                asyncio.run(fetch_old(app, storage, config))
            elif command == "segregate":
                segregate_messages(storage)
            elif command == "simplify":
                simplify_messages(storage)
            elif command == "exit":
                print("Exiting application.")
                break
            else:
                print("Unknown command. Try 'list', 'use', 'join', 'fetch', 'segregate', 'simplify', or 'exit'.")
    except Exception as e:
        print(f"Error: {e}")
    finally:
        print("Application exited.")


if __name__ == "__main__":
    main()