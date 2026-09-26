ALTER TABLE messages ADD COLUMN parent_message_id TEXT REFERENCES messages(id) ON DELETE SET NULL;
ALTER TABLE messages ADD COLUMN turn_id TEXT REFERENCES agent_turns(id) ON DELETE SET NULL;
ALTER TABLE messages ADD COLUMN updated_at REAL;
UPDATE messages SET updated_at = created_at WHERE updated_at IS NULL;
CREATE INDEX idx_messages_parent ON messages(conversation_id, parent_message_id, created_at);

CREATE TABLE conversation_branches (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    root_message_id TEXT REFERENCES messages(id) ON DELETE SET NULL,
    head_message_id TEXT REFERENCES messages(id) ON DELETE SET NULL,
    title TEXT NOT NULL DEFAULT '主线',
    is_active INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE INDEX idx_conversation_branches_conversation ON conversation_branches(conversation_id, updated_at);

ALTER TABLE agent_turns ADD COLUMN branch_id TEXT REFERENCES conversation_branches(id) ON DELETE SET NULL;
ALTER TABLE agent_turns ADD COLUMN cancel_requested INTEGER NOT NULL DEFAULT 0;
ALTER TABLE agent_turns ADD COLUMN resume_token TEXT;
CREATE INDEX idx_agent_turns_branch_status ON agent_turns(branch_id, status);
