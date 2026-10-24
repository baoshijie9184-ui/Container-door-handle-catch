-- Recovery image references are maintained by the locked Jenkins release workflow.
ALTER TABLE agent_fetch_image_command ADD COLUMN retention_protocol INT NOT NULL DEFAULT 3;
CREATE TABLE IF NOT EXISTS agent_fetch_image_retention (
 reference_id VARCHAR(96) COLLATE utf8mb4_bin NOT NULL,
 image_id VARCHAR(80) COLLATE utf8mb4_bin NOT NULL,
 reference_kind VARCHAR(24) NOT NULL,
 state VARCHAR(16) NOT NULL DEFAULT 'HELD',
 updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 PRIMARY KEY(reference_id,image_id),
 KEY idx_fetch_image_retention(image_id,state)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS agent_fetch_image_retention_control (
 control_id TINYINT NOT NULL PRIMARY KEY,
 state VARCHAR(16) NOT NULL DEFAULT 'COLLECTING',
 revision BIGINT NOT NULL DEFAULT 0,
 updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
INSERT IGNORE INTO agent_fetch_image_retention_control(control_id,state) VALUES(1,'COLLECTING');
CREATE TABLE IF NOT EXISTS agent_fetch_image_retention_event (
 id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
 request_id CHAR(32) COLLATE utf8mb4_bin NOT NULL,
 action_name VARCHAR(24) NOT NULL,
 image_id VARCHAR(80) COLLATE utf8mb4_bin NULL,
 created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 UNIQUE KEY uk_fetch_retention_event(request_id,action_name,image_id),
 KEY idx_fetch_retention_event(request_id,id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
