-- Actual V20 audit CREATE TABLE only; no unrelated account/department ALTER or invented FK.
CREATE TABLE organization_binding_audit (
    id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    user_id BIGINT NOT NULL,
    username VARCHAR(50) NOT NULL,
    actor_user_id BIGINT NOT NULL,
    actor_username VARCHAR(50) NOT NULL,
    before_employee_id BIGINT NULL,
    after_employee_id BIGINT NULL,
    binding_version INT NOT NULL,
    action VARCHAR(16) NOT NULL,
    created_at DATETIME NOT NULL,
    KEY idx_binding_audit_user_id (user_id, id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
