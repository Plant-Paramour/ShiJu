CREATE TABLE users (
    id TEXT PRIMARY KEY,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    display_name TEXT,
    created_at REAL NOT NULL DEFAULT (unixepoch())
);

CREATE TABLE conversations (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title TEXT NOT NULL DEFAULT '新建对话',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE INDEX idx_conversations_user_updated ON conversations(user_id, updated_at DESC);

CREATE TABLE messages (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
    content TEXT NOT NULL,
    created_at REAL NOT NULL
);
CREATE INDEX idx_messages_conversation_created ON messages(conversation_id, created_at);

CREATE TABLE poems (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    job_id TEXT,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    meter_type TEXT NOT NULL DEFAULT '',
    form_name TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL
);
CREATE INDEX idx_poems_user_created ON poems(user_id, created_at DESC);

ALTER TABLE jobs ADD COLUMN user_id TEXT REFERENCES users(id) ON DELETE SET NULL;
