CREATE TABLE IF NOT EXISTS embeddings_new (
    chat_id     INTEGER NOT NULL,
    message_id  INTEGER NOT NULL,
    chunk_idx   INTEGER NOT NULL DEFAULT 0,
    vector      BLOB    NOT NULL,
    model       TEXT    NOT NULL,
    PRIMARY KEY (chat_id, message_id, chunk_idx)
);

INSERT OR IGNORE INTO embeddings_new (chat_id, message_id, chunk_idx, vector, model)
    SELECT chat_id, message_id, 0, vector, model FROM embeddings;

DROP TABLE embeddings;
ALTER TABLE embeddings_new RENAME TO embeddings;

INSERT OR IGNORE INTO schema_version (version) VALUES (5);
