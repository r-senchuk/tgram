CREATE TABLE IF NOT EXISTS messages (
    chat_id                 INTEGER NOT NULL,
    id                      INTEGER NOT NULL,
    date                    TEXT NOT NULL,
    text                    TEXT,
    from_user_id            INTEGER,
    username                TEXT,
    reply_to_message_id     INTEGER,
    reply_to_top_message_id INTEGER,
    virtual_topic_id        INTEGER,
    media_type              TEXT,
    raw_json                TEXT NOT NULL,
    created_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (chat_id, id)
);

CREATE INDEX IF NOT EXISTS idx_messages_date          ON messages(date);
CREATE INDEX IF NOT EXISTS idx_messages_user          ON messages(from_user_id);
CREATE INDEX IF NOT EXISTS idx_messages_native_topic  ON messages(chat_id, reply_to_top_message_id);
CREATE INDEX IF NOT EXISTS idx_messages_virtual_topic ON messages(chat_id, virtual_topic_id);
CREATE INDEX IF NOT EXISTS idx_messages_reply         ON messages(chat_id, reply_to_message_id);

CREATE TABLE IF NOT EXISTS channels (
    chat_id            INTEGER PRIMARY KEY,
    title              TEXT,
    type               TEXT NOT NULL,
    is_forum           INTEGER NOT NULL DEFAULT 0,
    last_fetched_id    INTEGER,
    oldest_fetched_id  INTEGER,
    last_fetch_at      TIMESTAMP,
    enabled            INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS schema_version (
    version    INTEGER PRIMARY KEY,
    applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
INSERT OR IGNORE INTO schema_version (version) VALUES (1);
