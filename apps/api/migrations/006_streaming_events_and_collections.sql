CREATE TABLE agent_turns (
    id TEXT PRIMARY KEY,
    user_id TEXT REFERENCES users(id) ON DELETE CASCADE,
    conversation_id TEXT REFERENCES conversations(id) ON DELETE CASCADE,
    user_message_id TEXT REFERENCES messages(id) ON DELETE SET NULL,
    assistant_message_id TEXT REFERENCES messages(id) ON DELETE SET NULL,
    status TEXT NOT NULL DEFAULT 'running',
    last_event_seq INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE INDEX idx_agent_turns_conversation ON agent_turns(conversation_id, created_at);

CREATE TABLE agent_events (
    id TEXT PRIMARY KEY,
    turn_id TEXT NOT NULL REFERENCES agent_turns(id) ON DELETE CASCADE,
    seq INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at REAL NOT NULL,
    UNIQUE(turn_id, seq)
);
CREATE INDEX idx_agent_events_turn_seq ON agent_events(turn_id, seq);

CREATE TABLE job_candidates (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    ordinal INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued',
    attempt INTEGER NOT NULL DEFAULT 0,
    partial_text TEXT NOT NULL DEFAULT '',
    raw_text TEXT NOT NULL DEFAULT '',
    title TEXT,
    content TEXT,
    error TEXT,
    started_at REAL,
    finished_at REAL,
    updated_at REAL NOT NULL,
    UNIQUE(job_id, ordinal)
);
CREATE INDEX idx_job_candidates_job ON job_candidates(job_id, ordinal);

CREATE TABLE job_events (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    seq INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at REAL NOT NULL,
    UNIQUE(job_id, seq)
);
CREATE INDEX idx_job_events_job_seq ON job_events(job_id, seq);

CREATE TABLE conversation_folders (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE INDEX idx_conversation_folders_user ON conversation_folders(user_id, updated_at DESC);

ALTER TABLE conversations ADD COLUMN folder_id TEXT REFERENCES conversation_folders(id) ON DELETE SET NULL;
ALTER TABLE conversations ADD COLUMN deleted_at REAL;
CREATE INDEX idx_conversations_user_deleted_updated ON conversations(user_id, deleted_at, updated_at DESC);

CREATE TABLE poem_collections (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE TABLE poem_collection_items (
    collection_id TEXT NOT NULL REFERENCES poem_collections(id) ON DELETE CASCADE,
    poem_id TEXT NOT NULL REFERENCES poems(id) ON DELETE CASCADE,
    created_at REAL NOT NULL,
    PRIMARY KEY(collection_id, poem_id)
);
CREATE INDEX idx_collection_items_poem ON poem_collection_items(poem_id);

ALTER TABLE poems ADD COLUMN work_type TEXT NOT NULL DEFAULT '其他';
CREATE TABLE poem_favorites (
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    poem_id TEXT NOT NULL REFERENCES poems(id) ON DELETE CASCADE,
    created_at REAL NOT NULL,
    PRIMARY KEY(user_id, poem_id)
);
