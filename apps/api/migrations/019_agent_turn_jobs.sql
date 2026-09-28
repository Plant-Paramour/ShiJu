ALTER TABLE jobs ADD COLUMN agent_turn_id TEXT;
CREATE INDEX idx_jobs_agent_turn_id ON jobs(agent_turn_id, created_at);
