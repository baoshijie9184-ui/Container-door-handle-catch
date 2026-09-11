-- 与 Employee/Device 实体的乐观锁字段保持一致，避免 MyBatis-Plus 查询不存在的 version 列
USE doorhandledb;
SET @sql_employee = IF(
  (SELECT COUNT(*) FROM information_schema.columns WHERE table_schema = DATABASE() AND table_name = 'employee' AND column_name = 'version') = 0,
  'ALTER TABLE employee ADD COLUMN version INT NOT NULL DEFAULT 0 COMMENT ''乐观锁版本''',
  'SELECT 1'
);
PREPARE stmt_employee FROM @sql_employee;
EXECUTE stmt_employee;
DEALLOCATE PREPARE stmt_employee;

SET @sql_device = IF(
  (SELECT COUNT(*) FROM information_schema.columns WHERE table_schema = DATABASE() AND table_name = 'device_management' AND column_name = 'version') = 0,
  'ALTER TABLE device_management ADD COLUMN version INT NOT NULL DEFAULT 0 COMMENT ''乐观锁版本''',
  'SELECT 1'
);
PREPARE stmt_device FROM @sql_device;
EXECUTE stmt_device;
DEALLOCATE PREPARE stmt_device;
