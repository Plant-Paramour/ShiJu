ALTER TABLE job_candidates ADD COLUMN evaluation_json TEXT;

ALTER TABLE poems ADD COLUMN candidate_ordinal INTEGER;
ALTER TABLE poems ADD COLUMN evaluation_json TEXT;

UPDATE poems
SET candidate_ordinal = (
    SELECT COUNT(*)
    FROM poems AS earlier
    WHERE earlier.job_id = poems.job_id
      AND (
        earlier.created_at < poems.created_at
        OR (earlier.created_at = poems.created_at AND earlier.id <= poems.id)
      )
);

CREATE UNIQUE INDEX idx_poems_job_candidate
ON poems(job_id, candidate_ordinal);
