-- Roll back compact 002 before the old source table is contracted.
-- Maintenance window only: stop all old and new writers, back up current users and old
-- bindings, run with MySQL 8.4 stop-on-error (never --force), then deploy the old code.
-- New association changes are copied back, including unbound version histories.
-- The two-phase reassignment stays in one transaction so swapped employee assignments
-- do not hit the old unique key halfway through. Profile fields and timestamps are untouched.
-- DDL cannot be rolled back. If the final ALTER fails, keep both verified representations
-- and inspect; do not start an application against an assumed schema version.

DELIMITER $$
CREATE PROCEDURE compact_002_account_binding_rollback()
BEGIN
    DECLARE mismatch_count BIGINT DEFAULT 0;
    DECLARE EXIT HANDLER FOR SQLEXCEPTION
    BEGIN
        ROLLBACK;
        RESIGNAL;
    END;
    IF DATABASE() IS NULL OR @@SESSION.foreign_key_checks <> 1 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Choose an explicit database and enable foreign_key_checks';
    END IF;
    IF (SELECT COUNT(*) FROM information_schema.columns WHERE table_schema=DATABASE()
        AND table_name='users' AND column_name IN ('employee_id','binding_version','binding_history_present')) <> 3
       OR NOT EXISTS(SELECT 1 FROM information_schema.tables WHERE table_schema=DATABASE()
        AND table_name='account_employee_binding' AND table_type='BASE TABLE') THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Rollback requires the expanded users and retained source table';
    END IF;
    IF EXISTS(SELECT 1 FROM account_employee_binding b LEFT JOIN users u ON u.id=b.user_id
        WHERE u.id IS NULL) THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Retained source has an account absent from users; restore before rollback';
    END IF;

    START TRANSACTION;
    UPDATE account_employee_binding SET employee_id=NULL WHERE employee_id IS NOT NULL;
    INSERT INTO account_employee_binding(user_id,employee_id,version)
    SELECT u.id,u.employee_id,u.binding_version FROM users u
      LEFT JOIN account_employee_binding old_binding ON old_binding.user_id=u.id
     WHERE u.binding_history_present=TRUE
        OR old_binding.user_id IS NOT NULL
    ON DUPLICATE KEY UPDATE employee_id=VALUES(employee_id),version=VALUES(version);
    SELECT COUNT(*) INTO mismatch_count FROM users u
      LEFT JOIN account_employee_binding b ON b.user_id=u.id
     WHERE (b.user_id IS NOT NULL AND (NOT(b.employee_id <=> u.employee_id) OR b.version<>u.binding_version OR u.binding_history_present<>TRUE))
        OR (b.user_id IS NULL AND (u.employee_id IS NOT NULL OR u.binding_version<>0 OR u.binding_history_present<>FALSE));
    IF mismatch_count <> 0 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Rollback association copy did not match current users';
    END IF;
    COMMIT;

    ALTER TABLE users
        DROP FOREIGN KEY fk_users_employee,
        DROP CHECK ck_users_binding_version,
        DROP CHECK ck_users_binding_history,
        DROP INDEX uk_users_employee,
        DROP COLUMN employee_id,
        DROP COLUMN binding_version,
        DROP COLUMN binding_history_present;
    SELECT 'ROLLED_BACK_ASSOCIATIONS_PRESERVED' AS migration_status;
END$$
CALL compact_002_account_binding_rollback()$$
DROP PROCEDURE compact_002_account_binding_rollback$$
DELIMITER ;
