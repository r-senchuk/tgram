import sqlite3
import json
from pathlib import Path

class SQLiteMessageStorage:
    def __init__(self, db_path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
    
    def _init_db(self):
        """Initialize database with clean, optimized schema."""
        with sqlite3.connect(self.db_path) as conn:
            # Enable JSON1 extension for advanced JSON queries
            conn.enable_load_extension(True)
            try:
                # Try to load JSON1 extension (available in SQLite 3.38.0+)
                conn.load_extension("libsqlite3_json1")
            except sqlite3.OperationalError:
                # Fallback for older SQLite versions
                pass
            
            # Create the messages table with clean structure
            conn.execute('''
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY,
                    chat_id INTEGER NOT NULL,
                    reply_to_top_message_id INTEGER,  -- Native Telegram topic ID (for forum chats)
                    virtual_topic_id INTEGER,         -- Virtual topic based on reply chains
                    from_user_id INTEGER,
                    username TEXT,
                    date TEXT,
                    text TEXT,
                    media_type TEXT,
                    reply_to_message_id INTEGER,
                    raw_data TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Create optimized indexes for performance
            # Primary indexes
            conn.execute('CREATE INDEX IF NOT EXISTS idx_chat_id_id ON messages(chat_id, id)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_virtual_topic_id ON messages(virtual_topic_id)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_reply_to_top_message_id ON messages(reply_to_top_message_id)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_reply_to_message_id ON messages(reply_to_message_id)')
            
            # Composite indexes for common queries
            conn.execute('CREATE INDEX IF NOT EXISTS idx_chat_virtual_topic ON messages(chat_id, virtual_topic_id)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_chat_native_topic ON messages(chat_id, reply_to_top_message_id)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_virtual_topic_reply ON messages(virtual_topic_id, reply_to_message_id)')
            
            # Utility indexes
            conn.execute('CREATE INDEX IF NOT EXISTS idx_date ON messages(date)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_from_user_id ON messages(from_user_id)')
    
    def save_message(self, message_id, message_content):
        """Save a single message to SQLite storage."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute('''
                    INSERT OR REPLACE INTO messages 
                    (id, chat_id, reply_to_top_message_id, virtual_topic_id, from_user_id, username, date, text, media_type, 
                     reply_to_message_id, raw_data) 
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    message_id,
                    message_content.get('chat_id'),
                    message_content.get('reply_to_top_message_id'),
                    message_content.get('virtual_topic_id'),
                    message_content.get('from_user', {}).get('id'),
                    message_content.get('from_user', {}).get('username'),
                    message_content.get('date'),
                    message_content.get('text'),
                    message_content.get('media'),
                    message_content.get('reply_to_message_id'),
                    json.dumps(message_content, ensure_ascii=False)
                ))
                conn.commit()
        except Exception as e:
            print(f"Error saving message {message_id}: {e}")
            raise
    
    def load_message(self, message_id):
        """Load a single message by ID."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute('''
                    SELECT raw_data FROM messages WHERE id = ?
                ''', (message_id,))
                row = cursor.fetchone()
                if row:
                    return json.loads(row[0])
                return None
        except Exception as e:
            print(f"Error loading message {message_id}: {e}")
            return None
    
    def load_all_messages(self):
        """Load all stored messages."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute('''
                    SELECT id, raw_data FROM messages ORDER BY id
                ''')
                messages = {}
                for row in cursor.fetchall():
                    message_id, raw_data = row
                    messages[str(message_id)] = json.loads(raw_data)
                return messages
        except Exception as e:
            print(f"Error loading all messages: {e}")
            return {}
    
    def is_message_processed(self, message_id):
        """Check if a message ID has already been processed."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute('''
                    SELECT 1 FROM messages WHERE id = ?
                ''', (message_id,))
                return cursor.fetchone() is not None
        except Exception as e:
            print(f"Error checking message {message_id}: {e}")
            return False
    
    def find_gaps(self, chat_id=None):
        """Identify missing message ID ranges in the storage."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                query = "SELECT id FROM messages"
                params = []
                if chat_id:
                    query += " WHERE chat_id = ?"
                    params.append(chat_id)
                query += " ORDER BY id"
                
                cursor = conn.execute(query, params)
                ids = [row[0] for row in cursor.fetchall()]
                
                if len(ids) < 2:
                    return []
                
                gaps = []
                for i in range(1, len(ids)):
                    if ids[i] > ids[i-1] + 1:
                        gaps.append((ids[i-1] + 1, ids[i] - 1))
                return gaps
        except Exception as e:
            print(f"Error finding gaps: {e}")
            return []

    def get_messages_by_native_topic(self, chat_id, native_topic_id):
        """Get all messages for a specific native topic in a chat."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute('''
                    SELECT id, raw_data FROM messages 
                    WHERE chat_id = ? AND reply_to_top_message_id = ? 
                    ORDER BY id
                ''', (chat_id, native_topic_id))
                
                messages = {}
                for row in cursor.fetchall():
                    message_id, raw_data = row
                    messages[str(message_id)] = json.loads(raw_data)
                return messages
        except Exception as e:
            print(f"Error getting messages by native topic: {e}")
            return {}

    def get_native_topics_for_chat(self, chat_id):
        """Get all unique native topics for a specific chat."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute('''
                    SELECT DISTINCT reply_to_top_message_id FROM messages 
                    WHERE chat_id = ? AND reply_to_top_message_id IS NOT NULL
                    ORDER BY reply_to_top_message_id
                ''', (chat_id,))
                
                topics = [row[0] for row in cursor.fetchall()]
                return topics
        except Exception as e:
            print(f"Error getting native topics for chat: {e}")
            return []

    def get_native_topic_stats(self, chat_id):
        """Get message count statistics grouped by native topic."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute('''
                    SELECT reply_to_top_message_id, COUNT(*) as message_count 
                    FROM messages 
                    WHERE chat_id = ? AND reply_to_top_message_id IS NOT NULL
                    GROUP BY reply_to_top_message_id 
                    ORDER BY message_count DESC
                ''', (chat_id,))
                
                stats = {}
                for row in cursor.fetchall():
                    topic_id, count = row
                    stats[topic_id] = count
                return stats
        except Exception as e:
            print(f"Error getting native topic stats: {e}")
            return {}

    def get_native_topic_summary(self, chat_id, native_topic_id):
        """Get summary information for a native topic."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute('''
                    SELECT 
                        MIN(id) as first_message_id,
                        MAX(id) as last_message_id,
                        COUNT(*) as message_count,
                        COUNT(DISTINCT from_user_id) as participant_count,
                        MIN(date) as first_date,
                        MAX(date) as last_date
                    FROM messages 
                    WHERE chat_id = ? AND reply_to_top_message_id = ?
                ''', (chat_id, native_topic_id))
                
                row = cursor.fetchone()
                if row:
                    return {
                        'native_topic_id': native_topic_id,
                        'first_message_id': row[0],
                        'last_message_id': row[1],
                        'message_count': row[2],
                        'participant_count': row[3],
                        'first_date': row[4],
                        'last_date': row[5]
                    }
                return None
        except Exception as e:
            print(f"Error getting native topic summary: {e}")
            return None

    def get_virtual_topic_stats(self, chat_id):
        """Get message count statistics grouped by virtual topic."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute('''
                    SELECT virtual_topic_id, COUNT(*) as message_count 
                    FROM messages 
                    WHERE chat_id = ? AND virtual_topic_id IS NOT NULL
                    GROUP BY virtual_topic_id 
                    ORDER BY message_count DESC
                ''', (chat_id,))
                
                stats = {}
                for row in cursor.fetchall():
                    topic_id, count = row
                    stats[topic_id] = count
                return stats
        except Exception as e:
            print(f"Error getting virtual topic stats: {e}")
            return {}

    def get_virtual_topics_for_chat(self, chat_id):
        """Get all unique virtual topics for a specific chat."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute('''
                    SELECT DISTINCT virtual_topic_id FROM messages 
                    WHERE chat_id = ? AND virtual_topic_id IS NOT NULL
                    ORDER BY virtual_topic_id
                ''', (chat_id,))
                
                topics = [row[0] for row in cursor.fetchall()]
                return topics
        except Exception as e:
            print(f"Error getting virtual topics for chat: {e}")
            return []

    def get_messages_by_virtual_topic(self, chat_id, virtual_topic_id):
        """Get all messages for a specific virtual topic in a chat."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute('''
                    SELECT id, raw_data FROM messages 
                    WHERE chat_id = ? AND virtual_topic_id = ? 
                    ORDER BY id
                ''', (chat_id, virtual_topic_id))
                
                messages = {}
                for row in cursor.fetchall():
                    message_id, raw_data = row
                    messages[str(message_id)] = json.loads(raw_data)
                return messages
        except Exception as e:
            print(f"Error getting messages by virtual topic: {e}")
            return {}

    def get_virtual_topic_summary(self, chat_id, virtual_topic_id):
        """Get summary information for a virtual topic."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute('''
                    SELECT 
                        MIN(id) as first_message_id,
                        MAX(id) as last_message_id,
                        COUNT(*) as message_count,
                        COUNT(DISTINCT from_user_id) as participant_count,
                        MIN(date) as first_date,
                        MAX(date) as last_date
                    FROM messages 
                    WHERE chat_id = ? AND virtual_topic_id = ?
                ''', (chat_id, virtual_topic_id))
                
                row = cursor.fetchone()
                if row:
                    return {
                        'virtual_topic_id': virtual_topic_id,
                        'first_message_id': row[0],
                        'last_message_id': row[1],
                        'message_count': row[2],
                        'participant_count': row[3],
                        'first_date': row[4],
                        'last_date': row[5]
                    }
                return None
        except Exception as e:
            print(f"Error getting virtual topic summary: {e}")
            return None

    def get_native_topic_stats(self, chat_id):
        """Get message count statistics grouped by native Telegram topics."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute('''
                    SELECT reply_to_top_message_id, COUNT(*) as message_count 
                    FROM messages 
                    WHERE chat_id = ? AND reply_to_top_message_id IS NOT NULL
                    GROUP BY reply_to_top_message_id 
                    ORDER BY message_count DESC
                ''', (chat_id,))
                
                stats = {}
                for row in cursor.fetchall():
                    topic_id, count = row
                    stats[topic_id] = count
                return stats
        except Exception as e:
            print(f"Error getting native topic stats: {e}")
            return {}

    def get_native_topics_for_chat(self, chat_id):
        """Get all unique native topics for a specific chat."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute('''
                    SELECT DISTINCT reply_to_top_message_id FROM messages 
                    WHERE chat_id = ? AND reply_to_top_message_id IS NOT NULL
                    ORDER BY reply_to_top_message_id
                ''', (chat_id,))
                
                topics = [row[0] for row in cursor.fetchall()]
                return topics
        except Exception as e:
            print(f"Error getting native topics for chat: {e}")
            return []

    def get_messages_by_native_topic(self, chat_id, native_topic_id):
        """Get all messages for a specific native topic in a chat."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute('''
                    SELECT id, raw_data FROM messages 
                    WHERE chat_id = ? AND reply_to_top_message_id = ? 
                    ORDER BY id
                ''', (chat_id, native_topic_id))
                
                messages = {}
                for row in cursor.fetchall():
                    message_id, raw_data = row
                    messages[str(message_id)] = json.loads(raw_data)
                return messages
        except Exception as e:
            print(f"Error getting messages by native topic: {e}")
            return {}

    def get_native_topic_summary(self, chat_id, native_topic_id):
        """Get summary information for a native topic."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute('''
                    SELECT 
                        MIN(id) as first_message_id,
                        MAX(id) as last_message_id,
                        COUNT(*) as message_count,
                        COUNT(DISTINCT from_user_id) as participant_count,
                        MIN(date) as first_date,
                        MAX(date) as last_date
                    FROM messages 
                    WHERE chat_id = ? AND reply_to_top_message_id = ?
                ''', (chat_id, native_topic_id))
                
                row = cursor.fetchone()
                if row:
                    return {
                        'native_topic_id': native_topic_id,
                        'first_message_id': row[0],
                        'last_message_id': row[1],
                        'message_count': row[2],
                        'participant_count': row[3],
                        'first_date': row[4],
                        'last_date': row[5]
                    }
                return None
        except Exception as e:
            print(f"Error getting native topic summary: {e}")
            return None

    def get_hybrid_topic_stats(self, chat_id):
        """Get combined statistics showing both native and virtual topics."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                # Get native topic stats
                native_stats = self.get_native_topic_stats(chat_id)
                
                # Get virtual topic stats
                virtual_stats = self.get_virtual_topic_stats(chat_id)
                
                return {
                    'native_topics': native_stats,
                    'virtual_topics': virtual_stats,
                    'total_native_topics': len(native_stats),
                    'total_virtual_topics': len(virtual_stats),
                    'messages_with_native_topics': sum(native_stats.values()),
                    'messages_with_virtual_topics': sum(virtual_stats.values())
                }
        except Exception as e:
            print(f"Error getting hybrid topic stats: {e}")
            return {}