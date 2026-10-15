-- After V27. Apply each additive column once; the local migration helper checks information_schema.
ALTER TABLE agent_skill_download ADD COLUMN target_skill_id VARCHAR(64) NULL;
ALTER TABLE agent_skill_download ADD COLUMN expected_skill_revision INT NULL;
