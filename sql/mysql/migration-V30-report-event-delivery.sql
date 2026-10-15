-- After V21. Additive ALTER statements run once. The local helper checks columns/indexes.
ALTER TABLE detection_report_outbox ADD COLUMN attempts INT NOT NULL DEFAULT 0;
ALTER TABLE detection_report_outbox ADD COLUMN next_attempt_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP;
ALTER TABLE detection_report_outbox ADD COLUMN lease_token VARCHAR(64) NULL;
ALTER TABLE detection_report_outbox ADD COLUMN lease_expires_at DATETIME NULL;
ALTER TABLE detection_report_outbox ADD COLUMN delivered_at DATETIME NULL;
ALTER TABLE detection_report_outbox ADD COLUMN last_error_code VARCHAR(40) NULL;
CREATE INDEX idx_report_event_due ON detection_report_outbox(delivery_status,next_attempt_at);
CREATE INDEX idx_report_event_lease ON detection_report_outbox(delivery_status,lease_expires_at);
CREATE INDEX idx_report_event_report ON detection_report_outbox(report_id);

CREATE TABLE IF NOT EXISTS detection_report_event_receipt (
  event_id VARCHAR(64) NOT NULL PRIMARY KEY,
  report_id VARCHAR(64) NOT NULL, event_type VARCHAR(80) NOT NULL,
  report_version INT NOT NULL, payload_sha256 CHAR(64) NOT NULL,
  consumed_at DATETIME NOT NULL,
  UNIQUE KEY uk_report_event_version(report_id,report_version)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS detection_report_event_state (
  report_id VARCHAR(64) NOT NULL PRIMARY KEY, last_version INT NOT NULL,
  status VARCHAR(20) NOT NULL, last_event_id VARCHAR(64) NOT NULL,
  updated_at DATETIME NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
