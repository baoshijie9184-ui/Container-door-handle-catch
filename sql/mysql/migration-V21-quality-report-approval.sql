-- 单企业报告草稿和独立审批。新增表，不更改任务结果或放行状态。
CREATE TABLE IF NOT EXISTS detection_quality_report (
    id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    report_id VARCHAR(64) NOT NULL,
    previous_report_id VARCHAR(64) NULL,
    owner_user_id BIGINT NOT NULL,
    owner_username VARCHAR(50) NOT NULL,
    task_id VARCHAR(128) NOT NULL,
    title VARCHAR(120) NOT NULL,
    narrative TEXT NOT NULL,
    status VARCHAR(20) NOT NULL,
    version INT NOT NULL,
    source_json MEDIUMTEXT NOT NULL,
    source_sha256 CHAR(64) NOT NULL,
    snapshot_sha256 CHAR(64) NULL,
    submitted_at DATETIME NULL,
    decided_at DATETIME NULL,
    decider_user_id BIGINT NULL,
    decider_username VARCHAR(50) NULL,
    decision_reason VARCHAR(500) NULL,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL,
    UNIQUE KEY uk_quality_report_id (report_id),
    KEY idx_quality_report_owner (owner_user_id,id),
    KEY idx_quality_report_status (status,id),
    KEY idx_quality_report_task (task_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS detection_report_audit (
    id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    report_id VARCHAR(64) NOT NULL,
    actor_user_id BIGINT NOT NULL,
    actor_username VARCHAR(50) NOT NULL,
    action VARCHAR(24) NOT NULL,
    before_status VARCHAR(20) NULL,
    after_status VARCHAR(20) NOT NULL,
    report_version INT NOT NULL,
    reason VARCHAR(500) NULL,
    snapshot_sha256 CHAR(64) NULL,
    created_at DATETIME NOT NULL,
    KEY idx_report_audit_report (report_id,id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS detection_report_command (
    actor_user_id BIGINT NOT NULL,
    request_id VARCHAR(64) NOT NULL,
    command_sha256 CHAR(64) NOT NULL,
    report_id VARCHAR(64) NOT NULL,
    response_json MEDIUMTEXT NOT NULL,
    created_at DATETIME NOT NULL,
    PRIMARY KEY (actor_user_id, request_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS detection_report_confirmation (
    token CHAR(64) NOT NULL PRIMARY KEY,
    report_id VARCHAR(64) NOT NULL,
    actor_user_id BIGINT NOT NULL,
    report_version INT NOT NULL,
    snapshot_sha256 CHAR(64) NOT NULL,
    decision_sha256 CHAR(64) NOT NULL,
    expires_at DATETIME NOT NULL,
    used_at DATETIME NULL,
    KEY idx_report_confirmation_expiry (expires_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS detection_report_outbox (
    event_id VARCHAR(64) NOT NULL PRIMARY KEY,
    report_id VARCHAR(64) NOT NULL,
    event_type VARCHAR(80) NOT NULL,
    payload_json TEXT NOT NULL,
    delivery_status VARCHAR(20) NOT NULL DEFAULT 'PENDING',
    created_at DATETIME NOT NULL,
    KEY idx_report_outbox_pending (delivery_status,created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
