from pyrogram import Client
from fetcher.fetcher import TelegramFetcher
from fetcher.storage_file import FileKeyValueStorage
import os
import asyncio
from dotenv import load_dotenv

# Load environment variables
load_dotenv()
API_ID = os.getenv("API_ID")
API_HASH = os.getenv("API_HASH")
CHAT_ID = int(os.getenv("CHAT_ID"))
BATCH_SIZE = int(os.getenv("BATCH_SIZE"))
OUTPUT_DIR = os.getenv("OUTPUT_DIR")

# Initialize components
storage = FileKeyValueStorage(OUTPUT_DIR)

async def main():
    async with Client("my_session", api_id=API_ID, api_hash=API_HASH) as app:
        fetcher = TelegramFetcher(app=app, storage=storage, chat_id=CHAT_ID, batch_size=BATCH_SIZE)
        
        print("Telegram Fetcher Interactive CLI")
        print("Type 'help' for available commands.")

        while True:
            command = input("> ").strip().lower()
            if not command:
                continue

            args = command.split()
            cmd = args[0]
            params = args[1:]

            if cmd in ["fetch_new", "fn"]:
                await fetcher.fetch_new()

            elif cmd in ["fetch_old", "fo"]:
                await fetcher.fetch_old()

            elif cmd in ["fetch_scan", "fs"]:
                await fetcher.fetch_scan()

            elif cmd in ["fetch_gap", "fg"]:
                if len(params) != 2:
                    print("Usage: fetch_gap <start_id> <end_id>")
                    continue
                try:
                    start_id, end_id = int(params[0]), int(params[1])
                    await fetcher.fetch_gap(start_id, end_id)
                except ValueError:
                    print("Error: start_id and end_id must be integers.")

            elif cmd in ["list_chan", "lc"]:
                await fetcher.list_channels()

            elif cmd in ["status", "st"]:
                fetcher.show_status()

            elif cmd in ["exit", "quit", "q"]:
                print("Exiting gracefully...")
                await fetcher.stop_current_task()
                break

            elif cmd == "help":
                print("Available commands:")
                print("  fetch_new (fn)   - Fetch newest messages")
                print("  fetch_old (fo)   - Fetch oldest messages")
                print("  fetch_scan (fs)  - Scan for missing messages")
                print("  fetch_gap (fg) <start_id> <end_id> - Fetch specific gap")
                print("  list_chan (lc)   - List available channels")
                print("  status (st)      - Show status of ongoing tasks")
                print("  exit (q, quit)   - Exit application")

            else:
                print(f"Unknown command: {cmd}. Type 'help' for a list of commands.")

if __name__ == "__main__":
    asyncio.run(main())