WITH ranked AS (
    SELECT id,
           ROW_NUMBER() OVER (PARTITION BY conversation_id ORDER BY updated_at DESC, created_at DESC, id DESC) AS rank_no
    FROM conversation_branches
    WHERE is_active = 1
)
UPDATE conversation_branches
SET is_active = 0
WHERE id IN (SELECT id FROM ranked WHERE rank_no > 1);

CREATE UNIQUE INDEX IF NOT EXISTS uq_conversation_one_active_branch
ON conversation_branches(conversation_id)
WHERE is_active = 1;

CREATE INDEX IF NOT EXISTS idx_messages_conversation_parent
ON messages(conversation_id, parent_message_id, created_at, id);
