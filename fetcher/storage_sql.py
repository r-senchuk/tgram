import sqlite3
from pathlib import Path

class SQLiteMessageStorage:
    def __init__(self, db_path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
    
    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY,
                    chat_id INTEGER NOT NULL,
                    from_user_id INTEGER,
                    username TEXT,
                    date TEXT,
                    text TEXT,
                    media_type TEXT,
                    reply_to_message_id INTEGER,
                    raw_data TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    INDEX(chat_id, id),
                    INDEX(date),
                    INDEX(from_user_id)
                )
            ''')
    
    def save_message(self, message_id, message_content):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('''
                INSERT OR REPLACE INTO messages 
                (id, chat_id, from_user_id, username, date, text, media_type, 
                 reply_to_message_id, raw_data) 
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                message_id,
                message_content.get('chat_id'),
                message_content.get('from_user', {}).get('id'),
                message_content.get('from_user', {}).get('username'),
                message_content.get('date'),
                message_content.get('text'),
                message_content.get('media'),
                message_content.get('reply_to_message_id'),
                json.dumps(message_content)
            ))
    
    def find_gaps(self, chat_id=None):
        with sqlite3.connect(self.db_path) as conn:
            query = "SELECT id FROM messages"
            params = []
            if chat_id:
                query += " WHERE chat_id = ?"
                params.append(chat_id)
            query += " ORDER BY id"
            
            ids = [row[0] for row in conn.execute(query, params)]
            gaps = []
            for i in range(1, len(ids)):
                if ids[i] > ids[i-1] + 1:
                    gaps.append((ids[i-1] + 1, ids[i] - 1))
            return gaps