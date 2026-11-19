-- MySQL 8, compact employee directory. Run during the directory upgrade in strict mode.
-- Stage and validate every candidate before updating any employee rows.
DROP TEMPORARY TABLE IF EXISTS employee_number_upgrade;
CREATE TEMPORARY TABLE employee_number_upgrade (
    id BIGINT PRIMARY KEY,
    position_code VARCHAR(50) NOT NULL,
    old_number VARCHAR(50) NOT NULL,
    new_number VARCHAR(50) NOT NULL UNIQUE,
    CHECK (CHAR_LENGTH(TRIM(SUBSTRING(new_number, 5))) > 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

INSERT INTO employee_number_upgrade (id, position_code, old_number, new_number)
SELECT id, employee_type, employee_number, CONCAT(
    CASE employee_type WHEN 'SUPERVISOR' THEN 'SUP' WHEN 'DETECTION' THEN 'DET'
                       WHEN 'COLLECTION' THEN 'COL' WHEN 'MAINTENANCE' THEN 'MNT' END,
    '-', REGEXP_REPLACE(TRIM(employee_number), '^(EMP|SUP|DET|COL|MNT)-', '', 1, 1, 'i'))
FROM employee
WHERE employee_type IN ('SUPERVISOR', 'DETECTION', 'COLLECTION', 'MAINTENANCE');

UPDATE employee e
JOIN employee_number_upgrade n ON n.id = e.id AND n.position_code = e.employee_type
                              AND BINARY n.old_number = BINARY e.employee_number
SET e.employee_number = n.new_number, e.version = e.version + 1, e.updated_at = e.updated_at
WHERE BINARY n.old_number <> BINARY n.new_number;
DROP TEMPORARY TABLE employee_number_upgrade;
