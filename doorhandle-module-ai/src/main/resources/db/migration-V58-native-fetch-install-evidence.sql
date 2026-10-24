-- Non-destructive: retain native installer identity across application rollback.
-- Existing rows are gateway/JVM writers; never infer native children exited from a JVM PID.
ALTER TABLE agent_mcp_install_worker
 ADD COLUMN writer_transport VARCHAR(32) NOT NULL DEFAULT 'STREAMABLE_HTTP',
 ADD COLUMN native_pool_id CHAR(32) COLLATE utf8mb4_bin NULL;
ALTER TABLE agent_fetch_installation
 ADD COLUMN reserved_bytes BIGINT NOT NULL DEFAULT 2097152;
