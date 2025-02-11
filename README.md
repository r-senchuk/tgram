# Telegram Fetcher

## Overview

This application fetches messages from a specified Telegram channel and supports various commands to interactively or programmatically retrieve data.

## Features

- Fetch new messages until the latest is reached.
- Fetch old messages as far back as possible.
- Scan for gaps in message history.
- Fetch messages within a specific gap.
- List available channels.
- Supports both CLI arguments and interactive command execution.
- Gracefully handles interruptions and can stop ongoing fetch tasks.
- Tracks the last fetched message per session.

## Installation

1. Clone the repository:

   ```bash
   git clone https://github.com/yourusername/tgram.git
   cd tgram
   ```

2. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

3. Set up environment variables: Create a `.env` file and add the following:

   ```env
   API_ID=your_api_id
   API_HASH=your_api_hash
   CHAT_ID=your_chat_id
   BATCH_SIZE=100
   OUTPUT_DIR=./output
   ```

4. Run the application:

   ```bash
   python main.py
   ```

## Usage

### Interactive Mode

After running `python main.py`, the program waits for commands. Available commands:

- `fetch_new` - Fetches new messages until the latest is reached.
- `fetch_old` - Fetches old messages as far back as possible.
- `fetch_scan` - Scans for gaps in message history and outputs missing message ranges.
- `fetch_gap start_id end_id` - Fetches messages between `start_id` and `end_id`.
- `list_chan` - Displays channel names and IDs.
- `status` - Shows the status of any ongoing fetch processes.
- `stop` - Stops the current fetch task.
- `exit` - Gracefully stops ongoing tasks and exits the program.

### CLI Mode

Commands can also be executed directly via the command line:

```bash
python main.py fetch_new
python main.py fetch_old
python main.py fetch_scan
python main.py fetch_gap 1000 2000
python main.py list_chan
```

## Graceful Handling of Interruptions

- The program tracks the last fetched message to allow resumption.
- Fetch operations execute sequentially, ensuring consistency.
- The `stop` command stops an ongoing fetch process.
- The `exit` command terminates the program without requiring confirmation.

## Contributing

Pull requests are welcome! For major changes, please open an issue first to discuss your ideas.

## License

MIT License

