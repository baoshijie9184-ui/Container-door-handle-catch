-- Actual V40/V52 table statements; no legacy task ALTERs or invented target-shaped source.
CREATE TABLE operations_audit (
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
CREATE TABLE operations_file_delivery (
 id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
 delivery_id CHAR(36) COLLATE utf8mb4_bin NOT NULL,
 actor_user_id BIGINT NOT NULL,
 scope VARCHAR(16) NOT NULL,
 domain VARCHAR(48) NOT NULL,
 resource_id VARCHAR(160) COLLATE utf8mb4_bin NOT NULL,
 file_id VARCHAR(128) COLLATE utf8mb4_bin NULL,
 correlation_id VARCHAR(128) COLLATE utf8mb4_bin NOT NULL,
 resource_version BIGINT NULL,
 expected_bytes BIGINT NULL,
 accepted_bytes_lower_bound BIGINT NOT NULL DEFAULT 0,
 http_status INT NULL,
 state VARCHAR(32) NOT NULL,
 revision BIGINT NOT NULL DEFAULT 0,
 created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 UNIQUE KEY uk_file_delivery_id(delivery_id),
 KEY idx_file_delivery_owner(actor_user_id,id),
 KEY idx_file_delivery_pending(state,updated_at,id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
