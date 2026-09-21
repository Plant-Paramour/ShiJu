ALTER TABLE jobs ADD COLUMN conversation_id TEXT REFERENCES conversations(id) ON DELETE SET NULL;
CREATE INDEX idx_jobs_user_conversation_status ON jobs(user_id, conversation_id, status, created_at);

UPDATE jobs
SET conversation_id = (
    SELECT messages.conversation_id
    FROM messages
    WHERE instr(messages.content, jobs.id) > 0
    ORDER BY messages.created_at DESC
    LIMIT 1
)
WHERE conversation_id IS NULL;
