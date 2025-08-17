# Topic/Thread Functionality Implementation

## Overview

This document describes the implementation of topic/thread support in the Telegram Message Intelligence Pipeline. Topics allow messages to be organized by thread, which is essential for forum-style Telegram chats where messages are grouped by discussion topics.

## What Was Implemented

### 1. Database Schema Updates

**Added `topic_id` field to messages table:**
```sql
ALTER TABLE messages ADD COLUMN topic_id INTEGER;
```

**New database schema:**
```sql
CREATE TABLE messages (
    id INTEGER PRIMARY KEY,
    chat_id INTEGER NOT NULL,
    topic_id INTEGER,           -- NEW: Topic/thread ID
    from_user_id INTEGER,
    username TEXT,
    date TEXT,
    text TEXT,
    media_type TEXT,
    reply_to_message_id INTEGER,
    raw_data TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

**New indexes for performance:**
```sql
CREATE INDEX idx_chat_topic_id ON messages(chat_id, topic_id, id);
```

### 2. Message Processing Updates

**Enhanced `_process_message` method in `fetcher/fetcher.py`:**
```python
def _process_message(self, message):
    """Convert a message to a serializable dictionary."""
    return {
        "id": message.id,
        "chat_id": self.chat_id,
        "topic_id": getattr(message, 'topic_id', None),  # NEW: Extract topic_id
        "from_user": {
            "id": message.from_user.id if message.from_user else None,
            "username": message.from_user.username if message.from_user else None,
        },
        "date": message.date.strftime("%Y-%m-%dT%H:%M:%S") if message.date else None,
        "text": message.text,
        "media": str(message.media) if message.media else None,
        "reply_to_message_id": message.reply_to_message_id,
    }
```

### 3. New Storage Methods

**Added to `fetcher/storage_sql.py`:**

- `get_messages_by_topic(chat_id, topic_id)` - Get all messages for a specific topic
- `get_topics_for_chat(chat_id)` - Get all unique topics for a chat
- `get_message_stats_by_topic(chat_id)` - Get message count statistics by topic

### 4. New Fetcher Methods

**Added to `fetcher/fetcher.py`:**

- `list_topics()` - List available topics/threads for the current chat
- `fetch_by_topic(topic_id)` - Fetch messages for a specific topic

### 5. New CLI Commands

**Added to `main.py`:**

- `list_topics (lt)` - List available topics/threads
- `fetch_by_topic (fbt) <topic_id>` - Fetch messages for specific topic
- `topic_stats (ts)` - Show message statistics by topic

**Updated help system:**
```bash
./tgram.sh help
```

### 6. Database Migration Support

**Automatic schema migration:**
- Detects existing databases without `topic_id` column
- Automatically adds the column if missing
- Preserves existing data
- No manual intervention required

## How It Works

### 1. Topic Detection

The system automatically detects if a chat supports topics:
```python
if hasattr(chat, 'is_forum') and chat.is_forum:
    # Chat supports topics
    print("This is a forum chat that supports topics")
else:
    # Regular chat
    print("This chat does not support topics")
```

### 2. Message Organization

Messages with topics are stored with the following structure:
```json
{
    "id": 1001,
    "chat_id": -1002096326580,
    "topic_id": 1,           // Topic/thread ID
    "from_user": {"id": 123, "username": "user"},
    "date": "2025-08-15T09:50:42",
    "text": "Hello everyone!",
    "media": null,
    "reply_to_message_id": null
}
```

### 3. Topic-Based Queries

**Get messages by topic:**
```sql
SELECT * FROM messages 
WHERE chat_id = ? AND topic_id = ? 
ORDER BY id
```

**Get topic statistics:**
```sql
SELECT topic_id, COUNT(*) as message_count 
FROM messages 
WHERE chat_id = ? AND topic_id IS NOT NULL
GROUP BY topic_id 
ORDER BY message_count DESC
```

## Usage Examples

### 1. List Available Topics
```bash
./tgram.sh list_topics
```

### 2. Fetch Messages for Specific Topic
```bash
./tgram.sh fetch_by_topic 123
```

### 3. Get Topic Statistics
```bash
./tgram.sh topic_stats
```

### 4. Interactive Mode
```bash
./tgram.sh
> list_topics
> fetch_by_topic 1
> topic_stats
```

## Benefits

### 1. Message Organization
- ✅ Messages are properly organized by thread/topic
- ✅ Correct message sequence within each topic
- ✅ No more mixed-up conversation threads

### 2. Context Preservation
- ✅ Better context for AI processing
- ✅ Proper reply chain preservation
- ✅ Topic-based filtering and searching

### 3. Forum Support
- ✅ Support for forum-style Telegram chats
- ✅ Handles both regular and topic-based chats
- ✅ Automatic topic detection

### 4. Performance
- ✅ Optimized indexes for topic-based queries
- ✅ Efficient filtering by chat + topic + message ID
- ✅ Fast topic statistics generation

## Current Status

### ✅ Implemented
- Database schema with `topic_id` support
- Automatic database migration
- Topic detection and listing
- Topic-based message fetching
- Topic statistics
- CLI commands for topic management
- Comprehensive error handling
- Performance optimization with indexes

### 🔄 Ready for Use
- System automatically detects topic support
- Gracefully handles non-topic chats
- Ready to work with forum-style chats when available

### 📝 Testing Results
- **Current chat**: IT Club Wroclaw (UA) 🇺🇦 (regular supergroup)
- **Topic support**: No (expected for regular chats)
- **System status**: Ready and waiting for topic-enabled chats
- **Database**: Successfully migrated with `topic_id` column

## Future Enhancements

### 1. Topic Names
- Store topic names/descriptions
- Human-readable topic identification
- Topic metadata (creation date, creator, etc.)

### 2. Advanced Topic Features
- Topic-based search and filtering
- Topic analytics and insights
- Topic export functionality

### 3. AI Integration
- Topic-based summarization
- Topic clustering and classification
- Topic-based question answering

## Technical Details

### Database Migration
The system automatically handles database schema updates:
1. Checks if `topic_id` column exists
2. Adds column if missing using `ALTER TABLE`
3. Creates necessary indexes
4. Preserves all existing data

### Error Handling
- Graceful fallback for non-topic chats
- Comprehensive logging for debugging
- Safe database operations with transactions

### Performance
- Composite index on `(chat_id, topic_id, id)`
- Efficient topic-based queries
- Minimal impact on existing operations

## Conclusion

The topic/thread functionality has been successfully implemented and is ready for use. While the current test chat doesn't support topics (it's a regular supergroup), the system is fully prepared to handle forum-style chats with topics when they become available.

The implementation provides:
- **Seamless integration** with existing functionality
- **Automatic database migration** for existing installations
- **Comprehensive CLI support** for topic management
- **Performance optimization** for topic-based operations
- **Future-ready architecture** for advanced topic features

When you connect to a forum-style Telegram chat, the system will automatically detect topic support and begin organizing messages by topic, solving the original problem of message sequence preservation in threaded conversations.
