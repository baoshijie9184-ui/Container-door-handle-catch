-- Compact schema 002: embed the explicitly recorded account/employee association in users.
-- Requires the V20 source tables. Execute through the MySQL 8.4 client with stop-on-error,
-- never --force, after a verified backup and with ALL account/organization writers stopped.
-- First restore the real source into an isolated ECS database and validate there.
-- This file does not drop the source table. The whole-schema contract owns that step.
-- MySQL DDL commits independently. On failure preserve the source and inspect the partial
-- expansion; do not rerun blindly or assume ROLLBACK reverted ALTER TABLE.
-- No account, employee, role, password or historical name is inferred or rewritten.

DELIMITER $$
CREATE PROCEDURE compact_002_account_binding_expand()
BEGIN
    DECLARE source_count BIGINT DEFAULT 0;
    DECLARE mismatch_count BIGINT DEFAULT 0;
    DECLARE EXIT HANDLER FOR SQLEXCEPTION
    BEGIN
        ROLLBACK;
        RESIGNAL;
    END;

    IF DATABASE() IS NULL OR @@SESSION.foreign_key_checks <> 1 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Choose an explicit database and enable foreign_key_checks';
    END IF;
    IF (SELECT COUNT(*) FROM information_schema.tables
        WHERE table_schema=DATABASE() AND table_type='BASE TABLE'
          AND table_name IN ('users','employee','account_employee_binding')) <> 3 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Requires users, employee and the V20 binding source table';
    END IF;
    IF EXISTS(SELECT 1 FROM information_schema.columns WHERE table_schema=DATABASE()
        AND table_name='users' AND column_name IN ('employee_id','binding_version','binding_history_present')) THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Expansion columns already exist; inspect prior migration instead of overwriting';
    END IF;
    IF EXISTS(SELECT 1 FROM account_employee_binding b
        LEFT JOIN users u ON u.id=b.user_id LEFT JOIN employee e ON e.id=b.employee_id
        WHERE u.id IS NULL OR (b.employee_id IS NOT NULL AND e.id IS NULL)
           OR b.version IS NULL OR b.version < 0) THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Source has an orphaned or invalid explicit binding';
    END IF;
    IF EXISTS(SELECT employee_id FROM account_employee_binding
        WHERE employee_id IS NOT NULL GROUP BY employee_id HAVING COUNT(*)>1) THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Source assigns one employee to multiple accounts';
    END IF;
    SELECT COUNT(*) INTO source_count FROM account_employee_binding;

    ALTER TABLE users
        ADD COLUMN employee_id BIGINT NULL,
        ADD COLUMN binding_version INT NOT NULL DEFAULT 0,
        ADD COLUMN binding_history_present BOOLEAN NOT NULL DEFAULT FALSE,
        ADD UNIQUE KEY uk_users_employee (employee_id),
        ADD CONSTRAINT fk_users_employee FOREIGN KEY (employee_id) REFERENCES employee(id) ON DELETE RESTRICT,
        ADD CONSTRAINT ck_users_binding_version CHECK (binding_version >= 0),
        ADD CONSTRAINT ck_users_binding_history CHECK(binding_history_present IN (0,1) AND (binding_history_present=1 OR (binding_version=0 AND employee_id IS NULL)));

    START TRANSACTION;
    UPDATE users u JOIN account_employee_binding b ON b.user_id=u.id
       SET u.employee_id=b.employee_id, u.binding_version=b.version, u.binding_history_present=TRUE, u.updated_at=u.updated_at;
    SELECT COUNT(*) INTO mismatch_count
      FROM account_employee_binding b LEFT JOIN users u ON u.id=b.user_id
     WHERE u.id IS NULL OR NOT(u.employee_id <=> b.employee_id) OR u.binding_version<>b.version OR u.binding_history_present<>TRUE;
    IF mismatch_count <> 0 OR (SELECT COUNT(*) FROM account_employee_binding) <> source_count THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Binding source changed or association backfill mismatch';
    END IF;
    IF EXISTS(SELECT 1 FROM users u LEFT JOIN account_employee_binding b ON b.user_id=u.id
        WHERE b.user_id IS NULL AND (u.employee_id IS NOT NULL OR u.binding_version<>0 OR u.binding_history_present<>FALSE)) THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'An account without source binding acquired association state';
    END IF;
    COMMIT;

    SELECT 'EXPANDED_SOURCE_RETAINED' AS migration_status, source_count AS source_rows,
        (SELECT COUNT(*) FROM users WHERE employee_id IS NOT NULL) AS bound_accounts,
        (SELECT COUNT(*) FROM users WHERE binding_version>0) AS versioned_accounts;
END$$
CALL compact_002_account_binding_expand()$$
DROP PROCEDURE compact_002_account_binding_expand$$
DELIMITER ;
