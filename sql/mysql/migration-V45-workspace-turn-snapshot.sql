-- App-owned exact attachment boundaries for new assistant turns. Legacy turns are not backfilled by guessing time.
CREATE TABLE IF NOT EXISTS agent_workspace_turn_snapshot (
 id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
 user_id BIGINT NOT NULL,
 session_id VARCHAR(128) COLLATE utf8mb4_bin NOT NULL,
 message_id BIGINT NOT NULL,
 snapshot_json MEDIUMTEXT NOT NULL,
 snapshot_sha256 CHAR(64) NOT NULL,
 created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 UNIQUE KEY uk_workspace_turn(user_id,session_id,message_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
