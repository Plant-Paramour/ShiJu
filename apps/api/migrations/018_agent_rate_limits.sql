CREATE TABLE agent_rate_limit_requests (
    id TEXT PRIMARY KEY,
    identity_hash TEXT NOT NULL,
    created_at REAL NOT NULL,
    active INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX idx_agent_rate_limit_requests_active
ON agent_rate_limit_requests(active, identity_hash, created_at);
CREATE INDEX idx_agent_rate_limit_requests_created
ON agent_rate_limit_requests(created_at);
