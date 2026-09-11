-- 图片指纹和批量预检查基础表。执行前请确认数据库备份和当前 migration 顺序。
CREATE TABLE IF NOT EXISTS detection_image_fingerprint (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    sha256 CHAR(64) NOT NULL,
    file_name VARCHAR(255) NOT NULL,
    object_key VARCHAR(512) NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'NEW',
    last_task_id VARCHAR(64) NULL,
    owner_user_id VARCHAR(64) NULL,
    version INT NOT NULL DEFAULT 0,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_detection_image_sha256 (sha256),
    KEY idx_detection_image_status (status),
    KEY idx_detection_image_owner (owner_user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='检测图片指纹与最近检测状态';

CREATE TABLE IF NOT EXISTS detection_work_unit (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    work_unit_id VARCHAR(64) NOT NULL,
    source_batch_id VARCHAR(64) NULL,
    applicant_user_id VARCHAR(64) NOT NULL,
    assignee_user_id VARCHAR(64) NULL,
    image_count INT NOT NULL,
    completed_count INT NOT NULL DEFAULT 0,
    strategy VARCHAR(32) NOT NULL DEFAULT 'UNDETECTED_ONLY',
    status VARCHAR(32) NOT NULL DEFAULT 'WAITING',
    model_version VARCHAR(128) NULL,
    version INT NOT NULL DEFAULT 0,
    remark VARCHAR(1000) NULL,
    submitted_at DATETIME NULL,
    assigned_at DATETIME NULL,
    completed_at DATETIME NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_detection_work_unit_id (work_unit_id),
    KEY idx_detection_work_unit_status (status),
    KEY idx_detection_work_unit_user (applicant_user_id, assignee_user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='检测图片工作单元（最多5000张）';

CREATE TABLE IF NOT EXISTS detection_duplicate_ticket (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    ticket_id VARCHAR(64) NOT NULL,
    sha256 CHAR(64) NOT NULL,
    left_task_id VARCHAR(64) NOT NULL,
    right_task_id VARCHAR(64) NOT NULL,
    left_employee_id VARCHAR(64) NULL,
    right_employee_id VARCHAR(64) NULL,
    left_folder_name VARCHAR(255) NULL,
    right_folder_name VARCHAR(255) NULL,
    left_images_json JSON NULL,
    right_images_json JSON NULL,
    assigned_to VARCHAR(64) NULL,
    comparison_result VARCHAR(2000) NULL,
    resolution VARCHAR(32) NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'OPEN',
    approved_by VARCHAR(64) NULL,
    approved_at DATETIME NULL,
    version INT NOT NULL DEFAULT 0,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_detection_duplicate_ticket (ticket_id),
    KEY idx_detection_duplicate_status (status),
    KEY idx_detection_duplicate_sha256 (sha256)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='重复图片对比复查工单';

CREATE TABLE IF NOT EXISTS detection_work_unit_image (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    work_unit_id VARCHAR(64) NOT NULL,
    image_id VARCHAR(64) NOT NULL,
    file_name VARCHAR(255) NOT NULL,
    sha256 CHAR(64) NULL,
    object_key VARCHAR(512) NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'PENDING',
    detection_run_id VARCHAR(64) NULL,
    version INT NOT NULL DEFAULT 0,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_work_unit_image_id (image_id),
    KEY idx_work_unit_image_unit (work_unit_id),
    KEY idx_work_unit_image_hash (sha256)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='检测工作单元图片明细';
