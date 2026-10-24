-- V56: explicit stable-identity sources. Requires V40/V55.
-- Never infer old ownership, rewrite historical names, or enable a mode automatically.
CREATE TABLE IF NOT EXISTS detection_identity_binding_event (
 id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
 task_id VARCHAR(128) COLLATE utf8mb4_bin NOT NULL,
 identity_role VARCHAR(24) COLLATE utf8mb4_bin NOT NULL,
 revision BIGINT NOT NULL,
 bound_user_id BIGINT NULL,
 bound_identity_name VARCHAR(64) COLLATE utf8mb4_bin NULL,
 target_revision CHAR(64) COLLATE utf8mb4_bin NULL,
 actor_user_id BIGINT NULL,
 actor_name VARCHAR(64) COLLATE utf8mb4_bin NULL,
 source_kind VARCHAR(32) COLLATE utf8mb4_bin NOT NULL,
 request_id VARCHAR(128) COLLATE utf8mb4_bin NOT NULL,
 source_batch_id BIGINT UNSIGNED NULL,
 previous_sha256 CHAR(64) COLLATE utf8mb4_bin NOT NULL,
 event_sha256 CHAR(64) COLLATE utf8mb4_bin NOT NULL,
 created_at DATETIME(6) NOT NULL,
 UNIQUE KEY uk_identity_source_revision(task_id,identity_role,revision),
 UNIQUE KEY uk_identity_source_request(task_id,identity_role,request_id),
 KEY idx_identity_source_actor(actor_user_id,id),
 KEY idx_identity_source_batch(source_batch_id,id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS detection_identity_binding (
 id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
 task_id VARCHAR(128) COLLATE utf8mb4_bin NOT NULL,
 identity_role VARCHAR(24) COLLATE utf8mb4_bin NOT NULL,
 event_id BIGINT UNSIGNED NOT NULL,
 revision BIGINT NOT NULL,
 event_sha256 CHAR(64) COLLATE utf8mb4_bin NOT NULL,
 UNIQUE KEY uk_identity_binding_task_role(task_id,identity_role),
 UNIQUE KEY uk_identity_binding_event(event_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS detection_identity_source_control (
 control_id INT NOT NULL PRIMARY KEY,
 mode VARCHAR(16) COLLATE utf8mb4_bin NOT NULL DEFAULT 'COLLECTING',
 activation_revision BIGINT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
INSERT IGNORE INTO detection_identity_source_control(control_id,mode) VALUES(1,'COLLECTING');
