-- ============================================================
-- 数据库设计修复迁移脚本 V2
-- 修复 13 个数据库设计问题
-- 执行方式: 在 MySQL 中运行此脚本
-- ============================================================

USE doorhandledb;

-- ────────────────────────────────────────────────────────────
-- 问题2 [严重]: 聊天模块三张表添加外键约束
-- ────────────────────────────────────────────────────────────

-- chat_message.session_id -> chat_session.session_id
ALTER TABLE `chat_message`
    ADD CONSTRAINT `fk_chat_message_session`
    FOREIGN KEY (`session_id`) REFERENCES `chat_session` (`session_id`)
    ON DELETE CASCADE ON UPDATE CASCADE;

-- chat_pending_action.session_id -> chat_session.session_id
ALTER TABLE `chat_pending_action`
    ADD CONSTRAINT `fk_chat_pending_session`
    FOREIGN KEY (`session_id`) REFERENCES `chat_session` (`session_id`)
    ON DELETE CASCADE ON UPDATE CASCADE;

-- ────────────────────────────────────────────────────────────
-- 问题3 [中等]: detection_task.session_id 添加外键约束
-- ────────────────────────────────────────────────────────────

-- 先将无关联的 session_id 置空（允许 NULL）
UPDATE `detection_task` SET `session_id` = NULL
WHERE `session_id` IS NOT NULL
  AND `session_id` NOT IN (SELECT `session_id` FROM `chat_session`);

ALTER TABLE `detection_task`
    ADD CONSTRAINT `fk_detection_task_session`
    FOREIGN KEY (`session_id`) REFERENCES `chat_session` (`session_id`)
    ON DELETE SET NULL ON UPDATE CASCADE;

-- ────────────────────────────────────────────────────────────
-- 问题4 [中等]: chat_session.username 添加外键约束
-- ────────────────────────────────────────────────────────────

-- 清理无效用户名（如果存在）
-- UPDATE `chat_session` SET `username` = 'admin'
-- WHERE `username` NOT IN (SELECT `username` FROM `users`);

ALTER TABLE `chat_session`
    ADD CONSTRAINT `fk_chat_session_user`
    FOREIGN KEY (`username`) REFERENCES `users` (`username`)
    ON DELETE CASCADE ON UPDATE CASCADE;

-- ────────────────────────────────────────────────────────────
-- 问题5 [中等]: model_management 删除无用的 id 字段
-- 注意: 这是一个破坏性操作，需要确认没有代码依赖 id 字段
-- ────────────────────────────────────────────────────────────

-- 1. 删除外键约束（如果存在）
SET @fk_name = (SELECT CONSTRAINT_NAME FROM INFORMATION_SCHEMA.KEY_COLUMN_USAGE
    WHERE TABLE_NAME = 'detection_task' AND COLUMN_NAME = 'model_id'
    AND TABLE_SCHEMA = 'doorhandledb' AND REFERENCED_TABLE_NAME = 'model_management'
    LIMIT 1);
SET @sql = IF(@fk_name IS NOT NULL, CONCAT('ALTER TABLE `detection_task` DROP FOREIGN KEY `', @fk_name, '`'), 'SELECT 1');
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- 2. 删除 model_management 的自增 id 主键，改为 model_id 作为主键
ALTER TABLE `model_management` DROP PRIMARY KEY;
ALTER TABLE `model_management` DROP COLUMN `id`;
ALTER TABLE `model_management` ADD PRIMARY KEY (`model_id`);

-- 3. 重新添加外键约束
ALTER TABLE `detection_task`
    ADD CONSTRAINT `fk_detection_task_model`
    FOREIGN KEY (`model_id`) REFERENCES `model_management` (`model_id`)
    ON DELETE SET NULL ON UPDATE CASCADE;

-- ────────────────────────────────────────────────────────────
-- 问题8 [轻微]: Employee.hire_date 类型一致性
-- SQL 中是 DATE，Java 实体改为 LocalDate（代码层面修复，SQL 无需改动）
-- ────────────────────────────────────────────────────────────

-- ────────────────────────────────────────────────────────────
-- 问题10-11 [轻微]: 补充索引
-- ────────────────────────────────────────────────────────────

-- chat_message: 联合索引覆盖 WHERE session_id ORDER BY id
ALTER TABLE `chat_message`
    ADD INDEX `idx_chat_message_session_id_created_at` (`session_id`, `id`);

-- detection_task: created_by 索引
ALTER TABLE `detection_task`
    ADD INDEX `idx_detection_task_created_by` (`created_by`);

-- chat_session: status 索引
ALTER TABLE `chat_session`
    ADD INDEX `idx_chat_session_status` (`status`);

-- employee: employee_type 和 department 索引
ALTER TABLE `employee`
    ADD INDEX `idx_employee_type` (`employee_type`),
    ADD INDEX `idx_employee_department` (`department`);

-- device_management: status 和 device_type 索引
ALTER TABLE `device_management`
    ADD INDEX `idx_device_status` (`status`),
    ADD INDEX `idx_device_type` (`device_type`);

-- ────────────────────────────────────────────────────────────
-- 问题12-13 [轻微]: 统一 status 值为英文
-- device_management 和 device_usage_record 中文状态值改为英文
-- ────────────────────────────────────────────────────────────

-- device_management 状态映射: 使用中->IN_USE, 维护中->MAINTENANCE, 未使用->IDLE, 离线->OFFLINE
UPDATE `device_management` SET `status` = 'IN_USE' WHERE `status` = '使用中';
UPDATE `device_management` SET `status` = 'MAINTENANCE' WHERE `status` = '维护中';
UPDATE `device_management` SET `status` = 'IDLE' WHERE `status` = '未使用';
UPDATE `device_management` SET `status` = 'OFFLINE' WHERE `status` = '离线';
UPDATE `device_management` SET `status` = 'IDLE' WHERE `status` = '空闲';

-- device_usage_record 状态映射: 使用中->IN_USE, 已归还->RETURNED
UPDATE `device_usage_record` SET `status` = 'IN_USE' WHERE `status` = '使用中';
UPDATE `device_usage_record` SET `status` = 'RETURNED' WHERE `status` = '已归还';
