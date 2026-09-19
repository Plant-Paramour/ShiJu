CREATE TABLE jobs (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    status TEXT NOT NULL,
    request_json TEXT NOT NULL,
    request_hash TEXT NOT NULL,
    result_json TEXT,
    error_code TEXT,
    error_message TEXT,
    idempotency_key TEXT UNIQUE,
    attempts INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 2,
    worker_id TEXT,
    lease_expires_at REAL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    started_at REAL,
    finished_at REAL
);

CREATE INDEX idx_jobs_claim ON jobs(status, created_at);

CREATE TABLE workers (
    id TEXT PRIMARY KEY,
    capabilities_json TEXT NOT NULL,
    last_seen_at REAL NOT NULL
);
