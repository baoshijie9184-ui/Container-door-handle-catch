-- 与根目录 sql/mysql/migration-V16-management-optimistic-lock.sql 保持一致。
ALTER TABLE employee ADD COLUMN version INT NOT NULL DEFAULT 0 COMMENT '乐观锁版本';
ALTER TABLE device_management ADD COLUMN version INT NOT NULL DEFAULT 0 COMMENT '乐观锁版本';
