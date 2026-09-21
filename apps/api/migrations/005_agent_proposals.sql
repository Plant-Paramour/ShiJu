CREATE TABLE agent_proposals (
    conversation_id TEXT PRIMARY KEY REFERENCES conversations(id) ON DELETE CASCADE,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    proposal_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    prepared_turn INTEGER NOT NULL,
    submitted_job_id TEXT REFERENCES jobs(id) ON DELETE SET NULL,
    updated_at REAL NOT NULL
);
