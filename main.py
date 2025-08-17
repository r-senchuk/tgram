import logging
import os
import asyncio
from dotenv import load_dotenv
import sys
from pyrogram import Client
from fetcher.fetcher import TelegramFetcher
from fetcher.storage_sql import SQLiteMessageStorage

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('tgram.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()
logger.info("Environment variables loaded")
API_ID = os.getenv("API_ID")
API_HASH = os.getenv("API_HASH")
CHAT_ID = int(os.getenv("CHAT_ID"))
BATCH_SIZE = int(os.getenv("BATCH_SIZE"))
OUTPUT_DIR = os.getenv("OUTPUT_DIR")

# Initialize components - Now using SQLite storage
storage = SQLiteMessageStorage(f"{OUTPUT_DIR}/messages.db")

def print_help():
    print("Available commands:")
    print("  fetch_new (fn)   - Fetch newest messages")
    print("  fetch_old (fo)   - Fetch oldest messages")
    print("  fetch_scan (fs)  - Scan for missing messages")
    print("  fetch_gap (fg) <start_id> <end_id> - Fetch specific gap")
    print("  list_chan (lc)   - List available channels")
    print("  list_native_topics (lnt) - List native Telegram topics")
    print("  fetch_by_native_topic (fbnt) <topic_id> - Fetch messages for native topic")
    print("  native_topic_stats (nts) - Show native topic statistics")
    print("  list_virtual_topics (lvt) - List virtual topics based on reply chains")
    print("  fetch_by_virtual_topic (fbvt) <topic_id> - Fetch messages for virtual topic")
    print("  virtual_topic_stats (vts) - Show virtual topic statistics")
    print("  list_native_topics (lnt) - List native Telegram topics")
    print("  fetch_by_native_topic (fbnt) <topic_id> - Fetch messages for native topic")
    print("  native_topic_stats (nts) - Show native topic statistics")
    print("  hybrid_topic_stats (hts) - Show combined topic statistics")
    print("  status (st)      - Show stored message statistics")
    print("  exit (q, quit)   - Exit application")

def parse_command(raw_cmd):
    args = raw_cmd.strip().split()
    if not args:
        return None, []
    return args[0].lower(), args[1:]

async def handle_command(cmd, params, fetcher, interactive=True):
    logger.info(f"Handling command: {cmd} with params: {params}")
    
    if cmd in ["fetch_new", "fn"]:
        logger.info("Executing fetch_new command")
        await fetcher.fetch_new()
    elif cmd in ["fetch_old", "fo"]:
        logger.info("Executing fetch_old command")
        await fetcher.fetch_old()
    elif cmd in ["fetch_scan", "fs"]:
        logger.info("Executing fetch_scan command")
        await fetcher.fetch_scan()
    elif cmd in ["fetch_gap", "fg"]:
        if len(params) != 2:
            usage = "Usage: fetch_gap <start_id> <end_id>" if interactive else "Usage: python main.py fetch_gap <start_id> <end_id>"
            logger.warning(f"Invalid fetch_gap usage: {params}")
            print(usage)
            return False
        try:
            start_id, end_id = int(params[0]), int(params[1])
            logger.info(f"Executing fetch_gap command: {start_id} to {end_id}")
            await fetcher.fetch_gap(start_id, end_id)
        except ValueError:
            logger.error(f"Invalid fetch_gap parameters: {params}")
            print("Error: start_id and end_id must be integers.")
    elif cmd in ["list_chan", "lc"]:
        logger.info("Executing list_chan command")
        await fetcher.list_channels()

    elif cmd in ["virtual_topic_stats", "vts"]:
        logger.info("Executing virtual_topic_stats command")
        stats = fetcher.storage.get_virtual_topic_stats(fetcher.chat_id)
        if stats:
            print(f"Virtual topic statistics for chat {fetcher.chat_id}:")
            # Sort by message count (most active first)
            sorted_stats = sorted(stats.items(), key=lambda x: x[1], reverse=True)
            for topic_id, count in sorted_stats:
                print(f"  Virtual Topic {topic_id}: {count} messages")
        else:
            print("No virtual topic statistics available.")
    elif cmd in ["list_virtual_topics", "lvt"]:
        logger.info("Executing list_virtual_topics command")
        await fetcher.list_virtual_topics()
    elif cmd in ["fetch_by_virtual_topic", "fbvt"]:
        if len(params) != 1:
            usage = "Usage: fetch_by_virtual_topic <virtual_topic_id>" if interactive else "Usage: python main.py fetch_by_virtual_topic <virtual_topic_id>"
            logger.warning(f"Invalid fetch_by_virtual_topic usage: {params}")
            print(usage)
            return False
        try:
            virtual_topic_id = int(params[0])
            logger.info(f"Executing fetch_by_virtual_topic command: {virtual_topic_id}")
            await fetcher.fetch_by_virtual_topic(virtual_topic_id)
        except ValueError:
            logger.error(f"Invalid fetch_by_virtual_topic parameter: {params}")
            print("Error: virtual_topic_id must be an integer.")
    elif cmd in ["native_topic_stats", "nts"]:
        logger.info("Executing native_topic_stats command")
        stats = fetcher.storage.get_native_topic_stats(fetcher.chat_id)
        if stats:
            print(f"Native topic statistics for chat {fetcher.chat_id}:")
            # Sort by message count (most active first)
            sorted_stats = sorted(stats.items(), key=lambda x: x[1], reverse=True)
            for topic_id, count in sorted_stats:
                print(f"  Native Topic {topic_id}: {count} messages")
        else:
            print("No native topic statistics available.")
    elif cmd in ["list_native_topics", "lnt"]:
        logger.info("Executing list_native_topics command")
        await fetcher.list_native_topics()
    elif cmd in ["fetch_by_native_topic", "fbnt"]:
        if len(params) != 1:
            usage = "Usage: fetch_by_native_topic <native_topic_id>" if interactive else "Usage: python main.py fetch_by_native_topic <native_topic_id>"
            logger.warning(f"Invalid fetch_by_native_topic usage: {params}")
            print(usage)
            return False
        try:
            native_topic_id = int(params[0])
            logger.info(f"Executing fetch_by_native_topic command: {native_topic_id}")
            await fetcher.fetch_by_native_topic(native_topic_id)
        except ValueError:
            logger.error(f"Invalid fetch_by_native_topic parameter: {params}")
            print("Error: native_topic_id must be an integer.")
    elif cmd in ["hybrid_topic_stats", "hts"]:
        logger.info("Executing hybrid_topic_stats command")
        await fetcher.show_hybrid_topic_stats()
    elif cmd in ["status", "st"]:
        logger.info("Executing status command")
        fetcher.show_status()
    elif cmd in ["exit", "quit", "q"]:
        logger.info("Executing exit command")
        print("Exiting gracefully...")
        return True  # Signal to exit
    elif cmd == "help":
        logger.info("Executing help command")
        print_help()
    else:
        msg = f"Unknown command: {cmd}. Type 'help' for a list of commands."
        if not interactive:
            msg = f"Unknown or unsupported CLI command: {cmd}"
        logger.warning(f"Unknown command: {cmd}")
        print(msg)
    return False

def get_best_session_path():
    """Get the best available session path, prioritizing existing ones."""
    import glob
    import os
    
    sessions_dir = "/app/sessions"
    if not os.path.exists(sessions_dir):
        return f"{sessions_dir}/tgram_session"
    
    # Look for existing session files
    session_files = glob.glob(f"{sessions_dir}/tgram_session*.session")
    
    if session_files:
        # Use the most recent session file
        most_recent = max(session_files, key=os.path.getmtime)
        logger.info(f"Found existing session: {most_recent}")
        return most_recent.replace('.session', '')  # Remove .session extension
    else:
        # Use a simple, consistent session name
        new_session = f"{sessions_dir}/tgram_session"
        logger.info(f"Creating new session: {new_session}")
        return new_session

def cleanup_old_sessions():
    """Clean up old session files to prevent conflicts."""
    import glob
    import os
    
    sessions_dir = "/app/sessions"
    if os.path.exists(sessions_dir):
        # Remove old session files (keep only the last 3)
        session_files = glob.glob(f"{sessions_dir}/tgram_session_*.session")
        session_files.sort(key=os.path.getmtime, reverse=True)
        
        # Keep only the 3 most recent session files
        for old_file in session_files[3:]:
            try:
                os.remove(old_file)
                logger.info(f"Removed old session file: {old_file}")
            except Exception as e:
                logger.warning(f"Could not remove {old_file}: {e}")

async def test_session_validity(session_path):
    """Test if a session is valid by trying to connect."""
    try:
        from pyrogram import Client
        async with Client(session_path, api_id=API_ID, api_hash=API_HASH) as test_app:
            me = await test_app.get_me()
            logger.info(f"Session valid for user: {me.first_name}")
            return True
    except Exception as e:
        logger.warning(f"Session validation failed: {e}")
        return False

async def main():
    logger.info("Starting Telegram Fetcher application")
    
    # Clean up old session files
    cleanup_old_sessions()
    
    # Get the best available session path (prioritize existing ones)
    session_path = get_best_session_path()
    logger.info(f"Using session path: {session_path}")
    logger.info(f"Current working directory: {os.getcwd()}")
    
    # Test session validity if it exists
    if os.path.exists(f"{session_path}.session"):
        logger.info("Testing existing session validity...")
        if not await test_session_validity(session_path):
            logger.info("Existing session invalid, will create new one")
            # Remove invalid session file
            try:
                os.remove(f"{session_path}.session")
                if os.path.exists(f"{session_path}.session-journal"):
                    os.remove(f"{session_path}.session-journal")
                logger.info("Removed invalid session files")
            except Exception as e:
                logger.warning(f"Could not remove invalid session: {e}")
    
    try:
        logger.info("Initializing Pyrogram client...")
        async with Client(
            session_path, 
            api_id=API_ID, 
            api_hash=API_HASH
        ) as app:
            logger.info("Pyrogram client initialized successfully")
            
            # Test connection
            try:
                me = await app.get_me()
                logger.info(f"Connected as: {me.first_name} (@{me.username})")
            except Exception as e:
                logger.error(f"Failed to get user info: {e}")
                return
            
            fetcher = TelegramFetcher(app=app, storage=storage, chat_id=CHAT_ID, batch_size=BATCH_SIZE)
            logger.info("TelegramFetcher initialized")

            # CLI mode
            if len(sys.argv) > 1:
                cmd, params = sys.argv[1].lower(), sys.argv[2:]
                logger.info(f"CLI mode: executing command '{cmd}' with params {params}")
                should_exit = await handle_command(cmd, params, fetcher, interactive=False)
                return

            # Interactive mode
            logger.info("Starting interactive mode")
            print("Telegram Fetcher Interactive CLI")
            print("Type 'help' for available commands.")

            while True:
                command = input("> ")
                cmd, params = parse_command(command)
                if not cmd:
                    continue
                logger.info(f"Interactive command: '{cmd}' with params {params}")
                should_exit = await handle_command(cmd, params, fetcher, interactive=True)
                if should_exit:
                    break
                    
    except Exception as e:
        logger.error(f"Critical error in main: {e}", exc_info=True)
        raise

if __name__ == "__main__":
    asyncio.run(main())