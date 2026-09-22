ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'user';
ALTER TABLE users ADD COLUMN bio TEXT NOT NULL DEFAULT '';
ALTER TABLE users ADD COLUMN avatar_url TEXT;
ALTER TABLE users ADD COLUMN last_seen_at REAL;

CREATE TABLE forum_sections (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    slug TEXT NOT NULL UNIQUE,
    description TEXT NOT NULL DEFAULT '',
    sort_order INTEGER NOT NULL DEFAULT 0,
    is_locked INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE INDEX idx_forum_sections_order ON forum_sections(sort_order, created_at);

CREATE TABLE forum_threads (
    id TEXT PRIMARY KEY,
    section_id TEXT NOT NULL REFERENCES forum_sections(id) ON DELETE CASCADE,
    author_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    is_pinned INTEGER NOT NULL DEFAULT 0,
    is_locked INTEGER NOT NULL DEFAULT 0,
    view_count INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE INDEX idx_forum_threads_section ON forum_threads(section_id, is_pinned DESC, updated_at DESC);
CREATE INDEX idx_forum_threads_author ON forum_threads(author_id, created_at DESC);

CREATE TABLE forum_replies (
    id TEXT PRIMARY KEY,
    thread_id TEXT NOT NULL REFERENCES forum_threads(id) ON DELETE CASCADE,
    author_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    content TEXT NOT NULL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE INDEX idx_forum_replies_thread ON forum_replies(thread_id, created_at, id);

CREATE TABLE forum_permissions (
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    section_id TEXT NOT NULL REFERENCES forum_sections(id) ON DELETE CASCADE,
    permission TEXT NOT NULL DEFAULT 'read' CHECK(permission IN ('none','read','write','moderate')),
    updated_at REAL NOT NULL,
    PRIMARY KEY(user_id, section_id)
);

CREATE TABLE forum_follows (
    follower_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    followed_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at REAL NOT NULL,
    PRIMARY KEY(follower_id, followed_id),
    CHECK(follower_id <> followed_id)
);
CREATE INDEX idx_forum_follows_followed ON forum_follows(followed_id, created_at DESC);

CREATE TABLE forum_reports (
    id TEXT PRIMARY KEY,
    reporter_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    thread_id TEXT REFERENCES forum_threads(id) ON DELETE CASCADE,
    reply_id TEXT REFERENCES forum_replies(id) ON DELETE CASCADE,
    reason TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open','resolved','dismissed')),
    moderator_id TEXT REFERENCES users(id) ON DELETE SET NULL,
    resolution_note TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL,
    resolved_at REAL
);
CREATE INDEX idx_forum_reports_status ON forum_reports(status, created_at DESC);

INSERT OR IGNORE INTO forum_sections(id,name,slug,description,sort_order,created_at,updated_at)
VALUES ('general','诗友交流','general','分享创作、格律心得与灵感。',10,unixepoch(),unixepoch());
INSERT OR IGNORE INTO forum_sections(id,name,slug,description,sort_order,created_at,updated_at)
VALUES ('works','作品赏析','works','发布和讨论你的诗词作品。',20,unixepoch(),unixepoch());
INSERT OR IGNORE INTO forum_sections(id,name,slug,description,sort_order,created_at,updated_at)
VALUES ('feedback','产品反馈','feedback','反馈诗矩工具的使用体验与建议。',30,unixepoch(),unixepoch());
