-- 单企业账号、员工、部门关联。先执行现有 schema 和 V19 员工版本迁移。
-- 只按已有部门名称建立主数据，不猜测账号对应员工，不变更历史任务归属。
CREATE TABLE IF NOT EXISTS organization_department (
    id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_organization_department_name (name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

SET @org_column = IF((SELECT COUNT(*) FROM information_schema.columns
    WHERE table_schema=DATABASE() AND table_name='employee' AND column_name='department_id')=0,
    'ALTER TABLE employee ADD COLUMN department_id BIGINT NULL', 'SELECT 1');
PREPARE org_stmt FROM @org_column;
EXECUTE org_stmt;
DEALLOCATE PREPARE org_stmt;

INSERT INTO organization_department (name)
SELECT DISTINCT TRIM(e.department) FROM employee e
WHERE TRIM(COALESCE(e.department,''))<>''
AND NOT EXISTS (SELECT 1 FROM organization_department d WHERE d.name=TRIM(e.department));

UPDATE employee e JOIN organization_department d ON d.name=TRIM(e.department)
SET e.department_id=d.id, e.updated_at=e.updated_at WHERE e.department_id IS NULL;

SET @org_fk = IF((SELECT COUNT(*) FROM information_schema.table_constraints
    WHERE constraint_schema=DATABASE() AND table_name='employee' AND constraint_name='fk_employee_department')=0,
    'ALTER TABLE employee ADD CONSTRAINT fk_employee_department FOREIGN KEY (department_id) REFERENCES organization_department(id) ON DELETE RESTRICT', 'SELECT 1');
PREPARE org_stmt FROM @org_fk;
EXECUTE org_stmt;
DEALLOCATE PREPARE org_stmt;

CREATE TABLE IF NOT EXISTS account_employee_binding (
    user_id BIGINT NOT NULL PRIMARY KEY,
    employee_id BIGINT NULL,
    version INT NOT NULL DEFAULT 0,
    UNIQUE KEY uk_account_employee_binding_employee (employee_id),
    CONSTRAINT fk_binding_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE RESTRICT,
    CONSTRAINT fk_binding_employee FOREIGN KEY (employee_id) REFERENCES employee(id) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS organization_binding_audit (
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
