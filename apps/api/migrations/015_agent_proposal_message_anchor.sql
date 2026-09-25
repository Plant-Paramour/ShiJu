ALTER TABLE agent_proposals ADD COLUMN assistant_message_id TEXT REFERENCES messages(id) ON DELETE SET NULL;
