ALTER TABLE jobs ADD COLUMN cancel_requested INTEGER NOT NULL DEFAULT 0;

CREATE INDEX idx_jobs_cancel_requested ON jobs(status, cancel_requested);
