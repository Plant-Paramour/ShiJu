ALTER TABLE poems ADD COLUMN is_public INTEGER NOT NULL DEFAULT 0;
ALTER TABLE users ADD COLUMN notify_on_reaction INTEGER NOT NULL DEFAULT 1;

CREATE UNIQUE INDEX IF NOT EXISTS idx_users_display_name_unique
ON users(display_name COLLATE NOCASE)
WHERE display_name IS NOT NULL AND trim(display_name) <> '';

