ALTER TABLE messages ADD COLUMN status TEXT NOT NULL DEFAULT 'completed';
ALTER TABLE messages ADD COLUMN job_id TEXT REFERENCES jobs(id) ON DELETE SET NULL;
CREATE INDEX idx_messages_pending ON messages(conversation_id, status, created_at);
