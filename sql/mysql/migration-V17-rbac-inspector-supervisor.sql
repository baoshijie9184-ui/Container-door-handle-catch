-- V17: RBAC roles for inspection staff and detection supervisors.
-- Legacy ADMIN maps to SUPERVISOR; OPERATOR and unknown values map to INSPECTOR.
UPDATE `users`
SET `role` = CASE
    WHEN UPPER(`role`) IN ('ADMIN', 'SUPERVISOR') THEN 'SUPERVISOR'
    ELSE 'INSPECTOR'
END;

ALTER TABLE `users` MODIFY COLUMN `role` VARCHAR(16) NOT NULL DEFAULT 'INSPECTOR';
