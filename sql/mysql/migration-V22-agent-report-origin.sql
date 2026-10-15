-- 报告草稿和原始 Agent 调用关联；只新增表，不修改历史报告。
CREATE TABLE IF NOT EXISTS detection_report_agent_origin (
    actor_user_id BIGINT NOT NULL,
    request_id VARCHAR(64) NOT NULL,
    report_id VARCHAR(64) NOT NULL,
    report_version INT NOT NULL,
    run_id VARCHAR(128) NOT NULL,
    call_id VARCHAR(160) NOT NULL,
    tool_name VARCHAR(64) NOT NULL,
    created_at DATETIME NOT NULL,
    PRIMARY KEY (actor_user_id,request_id),
    KEY idx_report_origin_report (report_id,report_version),
    KEY idx_report_origin_run (run_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
