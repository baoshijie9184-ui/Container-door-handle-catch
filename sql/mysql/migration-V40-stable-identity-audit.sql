-- V40: additive identity and metadata audit foundation. No automatic ownership backfill.
CREATE TABLE IF NOT EXISTS operations_audit (
 id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
 actor_user_id BIGINT NOT NULL,
 scope VARCHAR(16) NOT NULL,
 domain VARCHAR(48) NOT NULL,
 action VARCHAR(64) NOT NULL,
 resource_id VARCHAR(160) NOT NULL,
 request_id VARCHAR(128) NOT NULL,
 result VARCHAR(40) NOT NULL,
 resource_version BIGINT NULL,
 created_at DATETIME(6) NOT NULL,
 UNIQUE KEY uk_operation_receipt(actor_user_id,domain,action,resource_id,request_id,result),
 KEY idx_operation_owner(actor_user_id,id),
 KEY idx_operation_domain(domain,id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
CREATE TABLE IF NOT EXISTS detection_identity_control (
 control_id INT PRIMARY KEY,
 mode VARCHAR(16) NOT NULL DEFAULT 'PREVIEW',
 revision BIGINT NOT NULL DEFAULT 0
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
INSERT IGNORE INTO detection_identity_control(control_id,mode,revision) VALUES(1,'PREVIEW',0);
CREATE TABLE IF NOT EXISTS detection_identity_command (
 request_id VARCHAR(128) PRIMARY KEY,
 actor_user_id BIGINT NOT NULL,
 request_sha256 CHAR(64) NOT NULL,
 result_json JSON NOT NULL,
 created_at DATETIME(6) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
SET @identity_ddl = IF((SELECT COUNT(*) FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='detection_task' AND column_name='created_user_id')=0,'ALTER TABLE detection_task ADD COLUMN created_user_id BIGINT NULL','SELECT 1');
PREPARE identity_stmt FROM @identity_ddl;
EXECUTE identity_stmt;
DEALLOCATE PREPARE identity_stmt;
SET @identity_ddl = IF((SELECT COUNT(*) FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='detection_task' AND column_name='created_identity_name')=0,'ALTER TABLE detection_task ADD COLUMN created_identity_name VARCHAR(64) COLLATE utf8mb4_bin NULL','SELECT 1');
PREPARE identity_stmt FROM @identity_ddl;
EXECUTE identity_stmt;
DEALLOCATE PREPARE identity_stmt;
SET @identity_ddl = IF((SELECT COUNT(*) FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='detection_task' AND column_name='assignee_user_id')=0,'ALTER TABLE detection_task ADD COLUMN assignee_user_id BIGINT NULL','SELECT 1');
PREPARE identity_stmt FROM @identity_ddl;
EXECUTE identity_stmt;
DEALLOCATE PREPARE identity_stmt;
SET @identity_ddl = IF((SELECT COUNT(*) FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='detection_task' AND column_name='assignee_identity_name')=0,'ALTER TABLE detection_task ADD COLUMN assignee_identity_name VARCHAR(64) COLLATE utf8mb4_bin NULL','SELECT 1');
PREPARE identity_stmt FROM @identity_ddl;
EXECUTE identity_stmt;
DEALLOCATE PREPARE identity_stmt;
SET @identity_ddl = IF((SELECT COUNT(*) FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='detection_task' AND column_name='reviewer_user_id')=0,'ALTER TABLE detection_task ADD COLUMN reviewer_user_id BIGINT NULL','SELECT 1');
PREPARE identity_stmt FROM @identity_ddl;
EXECUTE identity_stmt;
DEALLOCATE PREPARE identity_stmt;
SET @identity_ddl = IF((SELECT COUNT(*) FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='detection_task' AND column_name='reviewer_identity_name')=0,'ALTER TABLE detection_task ADD COLUMN reviewer_identity_name VARCHAR(64) COLLATE utf8mb4_bin NULL','SELECT 1');
PREPARE identity_stmt FROM @identity_ddl;
EXECUTE identity_stmt;
DEALLOCATE PREPARE identity_stmt;
SET @identity_ddl = IF((SELECT COUNT(*) FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='detection_task' AND column_name='disposition_user_id')=0,'ALTER TABLE detection_task ADD COLUMN disposition_user_id BIGINT NULL','SELECT 1');
PREPARE identity_stmt FROM @identity_ddl;
EXECUTE identity_stmt;
DEALLOCATE PREPARE identity_stmt;
SET @identity_ddl = IF((SELECT COUNT(*) FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='detection_task' AND column_name='disposition_identity_name')=0,'ALTER TABLE detection_task ADD COLUMN disposition_identity_name VARCHAR(64) COLLATE utf8mb4_bin NULL','SELECT 1');
PREPARE identity_stmt FROM @identity_ddl;
EXECUTE identity_stmt;
DEALLOCATE PREPARE identity_stmt;
SET @identity_ddl = IF((SELECT COUNT(*) FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='detection_task' AND column_name='rework_user_id')=0,'ALTER TABLE detection_task ADD COLUMN rework_user_id BIGINT NULL','SELECT 1');
PREPARE identity_stmt FROM @identity_ddl;
EXECUTE identity_stmt;
DEALLOCATE PREPARE identity_stmt;
SET @identity_ddl = IF((SELECT COUNT(*) FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='detection_task' AND column_name='rework_identity_name')=0,'ALTER TABLE detection_task ADD COLUMN rework_identity_name VARCHAR(64) COLLATE utf8mb4_bin NULL','SELECT 1');
PREPARE identity_stmt FROM @identity_ddl;
EXECUTE identity_stmt;
DEALLOCATE PREPARE identity_stmt;
SET @identity_ddl = IF((SELECT COUNT(*) FROM information_schema.statistics WHERE table_schema=DATABASE() AND table_name='detection_task' AND index_name='idx_detection_created_user')=0,'CREATE INDEX idx_detection_created_user ON detection_task(created_user_id,task_id)','SELECT 1');
PREPARE identity_stmt FROM @identity_ddl;
EXECUTE identity_stmt;
DEALLOCATE PREPARE identity_stmt;
SET @identity_ddl = IF((SELECT COUNT(*) FROM information_schema.statistics WHERE table_schema=DATABASE() AND table_name='detection_task' AND index_name='idx_detection_assignee_user')=0,'CREATE INDEX idx_detection_assignee_user ON detection_task(assignee_user_id,task_id)','SELECT 1');
PREPARE identity_stmt FROM @identity_ddl;
EXECUTE identity_stmt;
DEALLOCATE PREPARE identity_stmt;
