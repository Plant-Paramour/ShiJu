WITH ranked AS (
    SELECT
        id,
        ROW_NUMBER() OVER (
            PARTITION BY thread_id
            ORDER BY created_at, id
        ) AS floor_number
    FROM forum_replies
)
UPDATE forum_replies
SET floor_no = (
    SELECT ranked.floor_number
    FROM ranked
    WHERE ranked.id = forum_replies.id
);
