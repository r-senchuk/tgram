# Telegram Fetcher

## Overview

This application provides a robust command-line interface (CLI) for fetching and archiving messages from Telegram channels. It is designed for users who need to create a local backup of a channel's history, perform data analysis, or ensure a complete, gap-free message archive. The tool can be run interactively or through command-line arguments for automation.

## Features

- **Fetch New Messages**: Fetches all new messages from the last fetched message up to the most recent one in the channel.
- **Fetch Old Messages**: Fetches older messages, going backward in history from the earliest message stored locally.
- **Gap Detection**: Scans the locally stored message history to identify any gaps (missing message IDs) in the sequence.
- **Fill Gaps**: Fetches all messages within a specific ID range to fill identified gaps.
- **List Channels**: Lists all channels and chats you have access to, making it easy to find the correct `CHAT_ID`.
- **Interactive & CLI Modes**: Can be operated through an interactive command prompt or via direct CLI arguments for scripting.
- **Graceful Interruption Handling**: Long-running fetch operations can be stopped safely without corrupting data.
- **State Tracking**: Remembers the range of fetched messages for each channel to efficiently resume fetching.

## Project Structure

- `main.py`: Entry point providing both an interactive shell and direct CLI commands.
- `config.py`: Loads required environment variables and ensures output directories exist.
- `fetch_messages.py`: Standalone example script demonstrating lower-level message fetching.
- `fetcher/`
  - `fetcher.py`: Implements the `TelegramFetcher` class and fetcher interface.
  - `storage.py` / `storage_file.py`: Define the storage abstraction and JSON-backed implementation.
  - `channels.py`: Utilities for listing available channels and groups.
  - `utils.py`: Helper functions for JSON I/O, logging, ID-range checks, and environment loading.
- `tests/`
  - `test_fetcher.py` and `test_storage.py`: Unit tests covering fetch logic and file-based storage.

## Key Concepts

- Built on top of the asynchronous Pyrogram client for Telegram.
- Swappable storage backends via the `KeyValueStorage` interface; the default `FileKeyValueStorage` persists data to JSON.
- Multiple fetching modes (`fetch_new`, `fetch_old`, `fetch_scan`, `fetch_gap`, and `list_chan`) to archive messages and detect gaps.
- Commands are available through an interactive prompt or direct CLI invocation.

## Tips for New Contributors

1. Create a `.env` file with your Telegram API credentials, default `CHAT_ID`, `BATCH_SIZE`, and `OUTPUT_DIR`.
2. Review `fetcher/fetcher.py` to understand how messages are retrieved and stored asynchronously.
3. Run the unit tests with `python -m pytest` to ensure everything works after changes.
4. Check out `fetch_messages.py` for a lower-level example of message processing and consult the [Pyrogram documentation](https://docs.pyrogram.org/) to explore the broader API.

## Installation

- Clone the repository:

   ```bash
   git clone https://github.com/yourusername/tgram.git
   cd tgram
   ```

- Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

- Set up environment variables: Create a `.env` file in the root of the project.

## Configuration

Create a `.env` file with the following variables:

```env
# Your Telegram API credentials from my.telegram.org
API_ID=your_api_id
API_HASH=your_api_hash

# The ID of the default Telegram channel/chat to fetch from.
# You can find other IDs using the `list_chan` command.
CHAT_ID=your_chat_id

# Number of messages to fetch per API request.
BATCH_SIZE=100

# Directory to save the fetched message data.
OUTPUT_DIR=./output
```

- Run the application:

   ```bash
   python main.py
   ```

## Usage

### Interactive Mode

Run `python main.py` to start the interactive shell. You can then type commands at the prompt.

- `fetch_new`: Fetches messages with IDs greater than the highest ID stored locally for the current channel.
- `fetch_old`: Fetches messages with IDs lower than the lowest ID stored locally.
- `fetch_scan`: Scans the stored message database for the current channel and reports any ranges of missing message IDs.
- `fetch_gap <start_id> <end_id>`: Fetches all messages within the specified ID range. This is useful for filling gaps found by `fetch_scan`.
- `list_chan`: Displays the names and IDs of all your chats and channels.
- `status`: Shows whether a fetch operation is currently in progress.
- `exit`: Exits the application.

### CLI Mode

You can execute commands directly from your terminal for scripting or single-shot operations.

```bash
# Fetch new messages for the default CHAT_ID
python main.py fetch_new

# Fetch old messages
python main.py fetch_old

# Scan for gaps in message history
python main.py fetch_scan

# Fetch messages in a specific range
python main.py fetch_gap 1000 2000

# List available channels and chats
python main.py list_chan
```

## Graceful Handling of Interruptions

The application is designed to handle interruptions safely:

- **Stateful Resumption**: The application keeps track of the message ID ranges that have been successfully fetched for each channel. This allows `fetch_new` and `fetch_old` to resume exactly where they left off.
- **Sequential Operations**: Fetch requests are queued and executed one at a time to prevent conflicts and ensure data integrity.
- **Clean Exit**: The `exit` command ensures any running tasks are stopped before the program terminates.

## Contributing

Pull requests are welcome! For major changes, please open an issue first to discuss your ideas.

## License

MIT License
