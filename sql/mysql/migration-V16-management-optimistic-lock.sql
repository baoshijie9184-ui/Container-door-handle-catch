-- 员工、设备资料并发编辑保护。执行前请确认迁移工具已按版本顺序运行。
ALTER TABLE employee ADD COLUMN version INT NOT NULL DEFAULT 0 COMMENT '乐观锁版本';
ALTER TABLE device_management ADD COLUMN version INT NOT NULL DEFAULT 0 COMMENT '乐观锁版本';
