ALTER TABLE forum_threads ADD COLUMN is_featured INTEGER NOT NULL DEFAULT 0;
ALTER TABLE forum_threads ADD COLUMN deleted_at REAL;
ALTER TABLE forum_threads ADD COLUMN last_reply_id TEXT;
ALTER TABLE forum_threads ADD COLUMN last_reply_at REAL;
ALTER TABLE forum_threads ADD COLUMN last_reply_author_id TEXT;

ALTER TABLE forum_replies ADD COLUMN floor_no INTEGER;
ALTER TABLE forum_replies ADD COLUMN parent_reply_id TEXT REFERENCES forum_replies(id) ON DELETE SET NULL;
ALTER TABLE forum_replies ADD COLUMN quoted_reply_id TEXT REFERENCES forum_replies(id) ON DELETE SET NULL;
ALTER TABLE forum_replies ADD COLUMN deleted_at REAL;

CREATE TABLE IF NOT EXISTS forum_tags (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    slug TEXT NOT NULL UNIQUE,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS forum_thread_tags (
    thread_id TEXT NOT NULL REFERENCES forum_threads(id) ON DELETE CASCADE,
    tag_id TEXT NOT NULL REFERENCES forum_tags(id) ON DELETE CASCADE,
    PRIMARY KEY(thread_id, tag_id)
);
CREATE INDEX IF NOT EXISTS idx_forum_thread_tags_tag ON forum_thread_tags(tag_id, thread_id);

CREATE TABLE IF NOT EXISTS forum_content_poems (
    id TEXT PRIMARY KEY,
    thread_id TEXT REFERENCES forum_threads(id) ON DELETE CASCADE,
    reply_id TEXT REFERENCES forum_replies(id) ON DELETE CASCADE,
    poem_id TEXT NOT NULL REFERENCES poems(id) ON DELETE CASCADE,
    position INTEGER NOT NULL DEFAULT 0,
    CHECK((thread_id IS NOT NULL) != (reply_id IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS idx_forum_content_poems_thread ON forum_content_poems(thread_id, position);
CREATE INDEX IF NOT EXISTS idx_forum_content_poems_reply ON forum_content_poems(reply_id, position);

CREATE TABLE IF NOT EXISTS forum_thread_follows (
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    thread_id TEXT NOT NULL REFERENCES forum_threads(id) ON DELETE CASCADE,
    created_at REAL NOT NULL,
    PRIMARY KEY(user_id, thread_id)
);

CREATE TABLE IF NOT EXISTS forum_reactions (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    thread_id TEXT REFERENCES forum_threads(id) ON DELETE CASCADE,
    reply_id TEXT REFERENCES forum_replies(id) ON DELETE CASCADE,
    reaction_type TEXT NOT NULL CHECK(reaction_type IN ('like','question')),
    created_at REAL NOT NULL,
    CHECK((thread_id IS NOT NULL) != (reply_id IS NOT NULL) AND
          (thread_id IS NOT NULL OR reply_id IS NOT NULL)),
    UNIQUE(user_id, thread_id, reaction_type),
    UNIQUE(user_id, reply_id, reaction_type)
);
CREATE INDEX IF NOT EXISTS idx_forum_reactions_thread ON forum_reactions(thread_id, reaction_type);
CREATE INDEX IF NOT EXISTS idx_forum_reactions_reply ON forum_reactions(reply_id, reaction_type);

CREATE TABLE IF NOT EXISTS forum_notifications (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    actor_id TEXT REFERENCES users(id) ON DELETE SET NULL,
    notification_type TEXT NOT NULL,
    thread_id TEXT REFERENCES forum_threads(id) ON DELETE CASCADE,
    reply_id TEXT REFERENCES forum_replies(id) ON DELETE CASCADE,
    payload_json TEXT NOT NULL DEFAULT '{}',
    read_at REAL,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_forum_notifications_user ON forum_notifications(user_id, read_at, created_at DESC);

CREATE TABLE IF NOT EXISTS forum_drafts (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    kind TEXT NOT NULL CHECK(kind IN ('thread','reply')),
    thread_id TEXT REFERENCES forum_threads(id) ON DELETE CASCADE,
    section_id TEXT REFERENCES forum_sections(id) ON DELETE SET NULL,
    title TEXT NOT NULL DEFAULT '',
    content TEXT NOT NULL DEFAULT '',
    tags_json TEXT NOT NULL DEFAULT '[]',
    updated_at REAL NOT NULL,
    UNIQUE(user_id, kind, thread_id)
);
CREATE INDEX IF NOT EXISTS idx_forum_drafts_user ON forum_drafts(user_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS forum_section_moderators (
    section_id TEXT NOT NULL REFERENCES forum_sections(id) ON DELETE CASCADE,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at REAL NOT NULL,
    PRIMARY KEY(section_id, user_id)
);

CREATE TABLE IF NOT EXISTS forum_audit_logs (
    id TEXT PRIMARY KEY,
    actor_id TEXT REFERENCES users(id) ON DELETE SET NULL,
    action TEXT NOT NULL,
    section_id TEXT REFERENCES forum_sections(id) ON DELETE SET NULL,
    thread_id TEXT REFERENCES forum_threads(id) ON DELETE SET NULL,
    reply_id TEXT REFERENCES forum_replies(id) ON DELETE SET NULL,
    target_user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
    detail_json TEXT NOT NULL DEFAULT '{}',
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS forum_sensitive_words (
    id TEXT PRIMARY KEY,
    word TEXT NOT NULL UNIQUE,
    active INTEGER NOT NULL DEFAULT 1,
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS forum_rate_limits (
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    action TEXT NOT NULL,
    bucket_start INTEGER NOT NULL,
    count INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY(user_id, action, bucket_start)
);

CREATE TABLE IF NOT EXISTS auth_reset_tokens (
    token_hash TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    expires_at REAL NOT NULL,
    used_at REAL,
    created_at REAL NOT NULL
);
