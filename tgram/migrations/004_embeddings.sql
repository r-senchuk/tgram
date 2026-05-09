CREATE TABLE IF NOT EXISTS embeddings (
    chat_id     INTEGER NOT NULL,
    message_id  INTEGER NOT NULL,
    vector      BLOB    NOT NULL,
    model       TEXT    NOT NULL,
    PRIMARY KEY (chat_id, message_id)
);
