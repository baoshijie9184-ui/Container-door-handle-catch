-- Detection-owned additive identity evidence. Historical assigners are not inferred.
SET @assignment_ddl = IF((SELECT COUNT(*) FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='detection_task' AND column_name='assigned_by_user_id')=0,'ALTER TABLE detection_task ADD COLUMN assigned_by_user_id BIGINT NULL','SELECT 1');
PREPARE assignment_stmt FROM @assignment_ddl;
EXECUTE assignment_stmt;
DEALLOCATE PREPARE assignment_stmt;
SET @assignment_ddl = IF((SELECT COUNT(*) FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='detection_task' AND column_name='assigned_by_identity_name')=0,'ALTER TABLE detection_task ADD COLUMN assigned_by_identity_name VARCHAR(64) COLLATE utf8mb4_bin NULL','SELECT 1');
PREPARE assignment_stmt FROM @assignment_ddl;
EXECUTE assignment_stmt;
DEALLOCATE PREPARE assignment_stmt;
SET @assignment_ddl = IF((SELECT COUNT(*) FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='detection_task' AND column_name='assigned_to_revision')=0,'ALTER TABLE detection_task ADD COLUMN assigned_to_revision CHAR(64) COLLATE utf8mb4_bin NULL','SELECT 1');
PREPARE assignment_stmt FROM @assignment_ddl;
EXECUTE assignment_stmt;
DEALLOCATE PREPARE assignment_stmt;
SET @assignment_ddl = IF((SELECT COUNT(*) FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='detection_task' AND column_name='assignment_identity_revision')=0,'ALTER TABLE detection_task ADD COLUMN assignment_identity_revision BIGINT NOT NULL DEFAULT 0','SELECT 1');
PREPARE assignment_stmt FROM @assignment_ddl;
EXECUTE assignment_stmt;
DEALLOCATE PREPARE assignment_stmt;

CREATE TABLE IF NOT EXISTS detection_assignment_identity_event (
 id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
 task_id VARCHAR(128) COLLATE utf8mb4_bin NOT NULL,
 revision BIGINT NOT NULL,
 actor_user_id BIGINT NOT NULL,
 actor_name VARCHAR(64) COLLATE utf8mb4_bin NOT NULL,
 assignee_user_id BIGINT NOT NULL,
 assignee_name VARCHAR(64) COLLATE utf8mb4_bin NOT NULL,
 assignee_revision CHAR(64) COLLATE utf8mb4_bin NOT NULL,
 request_id VARCHAR(128) COLLATE utf8mb4_bin NOT NULL,
 created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 UNIQUE KEY uk_detection_assignment_revision(task_id,revision),
 UNIQUE KEY uk_detection_assignment_request(actor_user_id,request_id,task_id),
 KEY idx_detection_assignment_actor(actor_user_id,id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
