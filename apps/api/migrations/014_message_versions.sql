ALTER TABLE messages ADD COLUMN version_group_id TEXT;
ALTER TABLE messages ADD COLUMN version_number INTEGER NOT NULL DEFAULT 1;
UPDATE messages SET version_group_id = id WHERE version_group_id IS NULL;

CREATE TABLE message_versions (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    version_group_id TEXT NOT NULL,
    version_number INTEGER NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
    content TEXT NOT NULL,
    created_at REAL NOT NULL,
    UNIQUE(version_group_id, version_number)
);
CREATE INDEX idx_message_versions_group ON message_versions(version_group_id, version_number);
