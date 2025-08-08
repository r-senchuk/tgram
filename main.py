from pyrogram import Client
from fetcher.fetcher import TelegramFetcher
from fetcher.storage_file import FileKeyValueStorage
import os
import asyncio
from dotenv import load_dotenv
import sys

# Load environment variables
load_dotenv()
API_ID = os.getenv("API_ID")
API_HASH = os.getenv("API_HASH")
CHAT_ID = int(os.getenv("CHAT_ID"))
BATCH_SIZE = int(os.getenv("BATCH_SIZE"))
OUTPUT_DIR = os.getenv("OUTPUT_DIR")

# Initialize components
storage = FileKeyValueStorage(f"{OUTPUT_DIR}/messages.json")

def print_help():
    print("Available commands:")
    print("  fetch_new (fn)   - Fetch newest messages")
    print("  fetch_old (fo)   - Fetch oldest messages")
    print("  fetch_scan (fs)  - Scan for missing messages")
    print("  fetch_gap (fg) <start_id> <end_id> - Fetch specific gap")
    print("  list_chan (lc)   - List available channels")
    print("  status (st)      - Show stored message statistics")
    print("  exit (q, quit)   - Exit application")

def parse_command(raw_cmd):
    args = raw_cmd.strip().split()
    if not args:
        return None, []
    return args[0].lower(), args[1:]

async def handle_command(cmd, params, fetcher, interactive=True):
    if cmd in ["fetch_new", "fn"]:
        await fetcher.fetch_new()
    elif cmd in ["fetch_old", "fo"]:
        await fetcher.fetch_old()
    elif cmd in ["fetch_scan", "fs"]:
        await fetcher.fetch_scan()
    elif cmd in ["fetch_gap", "fg"]:
        if len(params) != 2:
            usage = "Usage: fetch_gap <start_id> <end_id>" if interactive else "Usage: python main.py fetch_gap <start_id> <end_id>"
            print(usage)
            return False
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
        return True  # Signal to exit
    elif cmd == "help":
        print_help()
    else:
        msg = f"Unknown command: {cmd}. Type 'help' for a list of commands."
        if not interactive:
            msg = f"Unknown or unsupported CLI command: {cmd}"
        print(msg)
    return False

async def main():
    async with Client("my_session", api_id=API_ID, api_hash=API_HASH) as app:
        fetcher = TelegramFetcher(app=app, storage=storage, chat_id=CHAT_ID, batch_size=BATCH_SIZE)

        # CLI mode
        if len(sys.argv) > 1:
            cmd, params = sys.argv[1].lower(), sys.argv[2:]
            should_exit = await handle_command(cmd, params, fetcher, interactive=False)
            return

        # Interactive mode
        print("Telegram Fetcher Interactive CLI")
        print("Type 'help' for available commands.")

        while True:
            command = input("> ")
            cmd, params = parse_command(command)
            if not cmd:
                continue
            should_exit = await handle_command(cmd, params, fetcher, interactive=True)
            if should_exit:
                break

if __name__ == "__main__":
    asyncio.run(main())