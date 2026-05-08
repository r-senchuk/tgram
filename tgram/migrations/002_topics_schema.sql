CREATE TABLE IF NOT EXISTS topics (
    chat_id   INTEGER NOT NULL,
    topic_id  INTEGER NOT NULL,
    title     TEXT NOT NULL,
    PRIMARY KEY (chat_id, topic_id)
);
INSERT OR IGNORE INTO schema_version (version) VALUES (2);
