-- 2026-xx-xx
-- Supervisor OSS project + batch + work unit split support

CREATE TABLE IF NOT EXISTS detection_project (
    id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    project_id VARCHAR(64) NOT NULL,
    project_name VARCHAR(128) NOT NULL,
    source_type VARCHAR(32) NOT NULL DEFAULT 'LOCAL_FOLDER',
    status VARCHAR(32) NOT NULL DEFAULT 'CREATED',
    oss_prefix VARCHAR(255) NULL,
    batch_size INT NOT NULL DEFAULT 5000,
    total_images INT NOT NULL DEFAULT 0,
    uploaded_images INT NOT NULL DEFAULT 0,
    batch_count INT NOT NULL DEFAULT 0,
    source_user_id VARCHAR(64) NULL,
    created_by VARCHAR(64) NOT NULL,
    closed_by VARCHAR(64) NULL,
    version INT NOT NULL DEFAULT 0,
    remark VARCHAR(500) NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_detection_project_id (project_id),
    KEY idx_detection_project_status (status),
    KEY idx_detection_project_creator_created (created_by, created_at),
    KEY idx_detection_project_source (source_type, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS detection_project_batch (
    id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    batch_id VARCHAR(64) NOT NULL,
    project_id VARCHAR(64) NOT NULL,
    batch_no INT NOT NULL,
    batch_name VARCHAR(128) NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'READY',
    assigned_status VARCHAR(32) NOT NULL DEFAULT 'UNASSIGNED',
    assignee_user_id VARCHAR(64) NULL,
    assignee_user_name VARCHAR(64) NULL,
    creator_user_id VARCHAR(64) NULL,
    worker_unit_id VARCHAR(64) NULL,
    image_count INT NOT NULL DEFAULT 0,
    uploaded_image_count INT NOT NULL DEFAULT 0,
    uploaded_file_count INT NOT NULL DEFAULT 0,
    oss_prefix VARCHAR(255) NULL,
    image_list_json LONGTEXT NULL,
    source_directory VARCHAR(255) NULL,
    version INT NOT NULL DEFAULT 0,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_detection_project_batch_id (batch_id),
    UNIQUE KEY uk_detection_project_batch_no (project_id, batch_no),
    KEY idx_detection_project_batch_status (project_id, status, created_at),
    KEY idx_detection_project_batch_assignee (assigned_status, assignee_user_id),
    KEY idx_detection_project_batch_creator (creator_user_id, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS detection_project_image (
    id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    project_id VARCHAR(64) NOT NULL,
    batch_id VARCHAR(64) NULL,
    image_id VARCHAR(64) NOT NULL,
    file_name VARCHAR(255) NOT NULL,
    relative_path VARCHAR(512) NOT NULL,
    object_key VARCHAR(512) NOT NULL,
    sha256 VARCHAR(64) NULL,
    file_size BIGINT NULL,
    source VARCHAR(32) NOT NULL DEFAULT 'LOCAL',
    status VARCHAR(32) NOT NULL DEFAULT 'PENDING',
    duplicate_reason VARCHAR(255) NULL,
    assigned_to VARCHAR(64) NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_detection_project_image_id (image_id),
    KEY idx_detection_project_image_project (project_id, status, created_at),
    KEY idx_detection_project_image_batch (batch_id, status),
    KEY idx_detection_project_image_sha (sha256)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

ALTER TABLE detection_work_unit
    ADD COLUMN IF NOT EXISTS project_id VARCHAR(64) NULL AFTER source_batch_id,
    ADD COLUMN IF NOT EXISTS batch_id VARCHAR(64) NULL AFTER project_id,
    ADD COLUMN IF NOT EXISTS assigned_user_name VARCHAR(64) NULL AFTER assignee_user_id;

ALTER TABLE detection_work_unit
    ADD INDEX IF NOT EXISTS idx_detection_work_unit_project (project_id),
    ADD INDEX IF NOT EXISTS idx_detection_work_unit_batch (batch_id),
    ADD INDEX IF NOT EXISTS idx_detection_work_unit_unassigned (status, assignee_user_id, created_at);

