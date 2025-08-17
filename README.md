# Telegram Message Intelligence Pipeline

## Overview

This application provides a robust command-line interface (CLI) for fetching and archiving messages from Telegram channels with intelligent topic organization. It is designed for users who need to create a local backup of a channel's history, perform data analysis, organize conversations by topics, or ensure a complete, gap-free message archive. The tool can be run interactively or through command-line arguments for automation.

## Features

### Core Message Fetching
- **Fetch New Messages**: Fetches all new messages from the last fetched message up to the most recent one in the channel.
- **Fetch Old Messages**: Fetches older messages, going backward in history from the earliest message stored locally.
- **Gap Detection**: Scans the locally stored message history to identify any gaps (missing message IDs) in the sequence.
- **Fill Gaps**: Fetches all messages within a specific ID range to fill identified gaps.
- **List Channels**: Lists all channels and chats you have access to, making it easy to find the correct `CHAT_ID`.

### Intelligent Topic Organization
- **Native Topic Support**: Automatically detects and organizes messages by native Telegram forum topics (when available).
- **Virtual Topic Analysis**: Creates logical conversation threads based on reply chains for any chat type.
- **Hybrid Topic System**: Combines both native and virtual topic approaches for comprehensive organization.
- **Topic Statistics**: Provides detailed analytics on message distribution across topics.

### User Experience
- **Interactive & CLI Modes**: Can be operated through an interactive command prompt or via direct CLI arguments for scripting.
- **Graceful Interruption Handling**: Long-running fetch operations can be stopped safely without corrupting data.
- **State Tracking**: Remembers the range of fetched messages for each channel to efficiently resume fetching.
- **Docker Support**: Containerized deployment for consistent environments.

## Project Structure

### Core Application
- `main.py`: Entry point providing both an interactive shell and direct CLI commands with topic support.
- `tgram.sh`: Convenient wrapper script for Docker operations and CLI commands.
- `config.py`: Loads required environment variables and ensures output directories exist.

### Fetcher Module
- `fetcher/fetcher.py`: Implements the `TelegramFetcher` class with native and virtual topic support.
- `fetcher/storage_sql.py`: SQLite-based storage with JSON1 extension for efficient message storage and topic organization.
- `fetcher/storage.py`: Abstract base class defining the storage interface.
- `fetcher/channels.py`: Utilities for listing available channels and groups.
- `fetcher/utils.py`: Helper functions for logging, ID-range checks, and environment loading.

### Infrastructure
- `Dockerfile`: Container definition with SQLite and JSON1 support.
- `docker-compose.yml`: Container orchestration with volume mounts for data persistence.
- `requirements.txt`: Python dependencies including Pyrogram and SQLite support.

### Documentation
- `docs/`: Comprehensive documentation covering storage requirements, topic implementation, and pipeline overview.

## Key Concepts

- **Pyrogram Integration**: Built on top of the asynchronous Pyrogram client for Telegram API access.
- **SQLite Storage**: Modern SQLite-based storage with JSON1 extension for efficient message storage and querying.
- **Topic Organization**: Intelligent message organization using both native Telegram topics and virtual topic analysis.
- **Multiple Fetching Modes**: Various commands (`fetch_new`, `fetch_old`, `fetch_scan`, `fetch_gap`, `list_chan`) to archive messages and detect gaps.
- **Docker Deployment**: Containerized application for consistent deployment across environments.
- **Hybrid Topic System**: Combines native forum topics with reply-chain analysis for comprehensive conversation organization.

## Tips for New Contributors

1. Create a `.env` file with your Telegram API credentials, default `CHAT_ID`, `BATCH_SIZE`, and `OUTPUT_DIR`.
2. Review `fetcher/fetcher.py` to understand how messages are retrieved and stored asynchronously with topic support.
3. Use Docker for consistent development: `./tgram.sh build` and `./tgram.sh shell`.
4. Check the `docs/` folder for detailed implementation guides and architecture overview.
5. Consult the [Pyrogram documentation](https://docs.pyrogram.org/) to explore the broader API.

## Installation

### Option 1: Docker (Recommended)

```bash
# Clone the repository
git clone https://github.com/yourusername/tgram.git
cd tgram

# Build the Docker image
./tgram.sh build

# Set up environment variables: Create a .env file in the root of the project
```

### Option 2: Local Installation

```bash
# Clone the repository
git clone https://github.com/yourusername/tgram.git
cd tgram

# Install dependencies
pip install -r requirements.txt

# Set up environment variables: Create a .env file in the root of the project
```

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

# Directory to save the fetched message data (for local installation only).
OUTPUT_DIR=./data
```

### Running the Application

#### Docker (Recommended)
```bash
# Interactive mode
./tgram.sh shell

# Direct commands
./tgram.sh fetch_new
./tgram.sh list_virtual_topics
./tgram.sh hybrid_topic_stats
```

#### Local Installation
```bash
# Interactive mode
python main.py

# Direct commands
python main.py fetch_new
python main.py list_virtual_topics
python main.py hybrid_topic_stats
```

## Usage

### Interactive Mode

Run `./tgram.sh shell` (Docker) or `python main.py` (local) to start the interactive shell. You can then type commands at the prompt.

#### Core Commands
- `fetch_new`: Fetches messages with IDs greater than the highest ID stored locally for the current channel.
- `fetch_old`: Fetches messages with IDs lower than the lowest ID stored locally.
- `fetch_scan`: Scans the stored message database for the current channel and reports any ranges of missing message IDs.
- `fetch_gap <start_id> <end_id>`: Fetches all messages within the specified ID range. This is useful for filling gaps found by `fetch_scan`.
- `list_chan`: Displays the names and IDs of all your chats and channels.
- `status`: Shows a summary of stored messages and any gaps detected.

#### Topic Organization Commands
- `list_native_topics (lnt)`: Lists available native Telegram forum topics (when supported).
- `fetch_by_native_topic <id> (fbnt)`: Fetches messages for a specific native topic.
- `native_topic_stats (nts)`: Shows statistics for native topics.
- `list_virtual_topics (lvt)`: Lists virtual topics based on reply chain analysis.
- `fetch_by_virtual_topic <id> (fbvt)`: Fetches messages for a specific virtual topic.
- `virtual_topic_stats (vts)`: Shows statistics for virtual topics.
- `hybrid_topic_stats (hts)`: Shows combined statistics for both topic systems.

- `exit`: Exits the application.

### CLI Mode

You can execute commands directly from your terminal for scripting or single-shot operations.

#### Docker Commands
```bash
# Fetch new messages for the default CHAT_ID
./tgram.sh fetch_new

# Fetch old messages
./tgram.sh fetch_old

# Scan for gaps in message history
./tgram.sh fetch_scan

# Fetch messages in a specific range
./tgram.sh fetch_gap 1000 2000

# List available channels and chats
./tgram.sh list_chan

# Show stored message statistics
./tgram.sh status

# Topic organization
./tgram.sh list_virtual_topics
./tgram.sh virtual_topic_stats
./tgram.sh hybrid_topic_stats
```

#### Local Commands
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

# Show stored message statistics
python main.py status

# Topic organization
python main.py list_virtual_topics
python main.py virtual_topic_stats
python main.py hybrid_topic_stats
```

## Topic Organization System

The application provides intelligent message organization through a hybrid topic system:

### Native Topics
- **Automatic Detection**: Automatically identifies native Telegram forum topics when available.
- **Forum Support**: Works with Telegram's built-in forum functionality for organized discussions.
- **API Integration**: Uses `reply_to_top_message_id` from the Telegram API for native topic identification.

### Virtual Topics
- **Reply Chain Analysis**: Creates logical conversation threads based on message reply relationships.
- **Universal Support**: Works with any chat type, not just forums.
- **Smart Grouping**: Automatically groups related messages into coherent conversation threads.

### Hybrid Approach
- **Best of Both Worlds**: Combines native and virtual topic systems for comprehensive organization.
- **Automatic Fallback**: Uses virtual topics when native topics aren't available.
- **Unified Statistics**: Provides combined analytics through `hybrid_topic_stats`.

## Docker Usage

The application includes comprehensive Docker support for consistent deployment:

### Quick Start
```bash
# Build the image
./tgram.sh build

# Start interactive shell
./tgram.sh shell

# Run commands directly
./tgram.sh fetch_new
./tgram.sh list_virtual_topics
```

### Volume Management
- **Data Persistence**: `./data` directory persists SQLite database across container restarts.
- **Session Persistence**: `./sessions` directory maintains Telegram authentication sessions.
- **Environment Variables**: Supports `.env` file for configuration.

## Graceful Handling of Interruptions

The application is designed to handle interruptions safely:

- **Stateful Resumption**: The application keeps track of the message ID ranges that have been successfully fetched for each channel. This allows `fetch_new` and `fetch_old` to resume exactly where they left off.
- **Sequential Operations**: Fetch requests are queued and executed one at a time to prevent conflicts and ensure data integrity.
- **Clean Exit**: The `exit` command ensures any running tasks are stopped before the program terminates.

## Contributing

Pull requests are welcome! For major changes, please open an issue first to discuss your ideas.

### Development Setup
1. **Fork and clone** the repository
2. **Use Docker** for consistent development: `./tgram.sh build && ./tgram.sh shell`
3. **Check documentation** in the `docs/` folder for implementation details
4. **Test functionality** with the available CLI commands
5. **Submit PR** with clear description of changes

### Architecture Overview
- **Storage Layer**: SQLite with JSON1 extension for efficient message storage
- **Topic System**: Hybrid approach combining native and virtual topic detection
- **CLI Interface**: Unified command handling in `main.py`
- **Docker Support**: Containerized deployment with volume persistence

## License

MIT License
