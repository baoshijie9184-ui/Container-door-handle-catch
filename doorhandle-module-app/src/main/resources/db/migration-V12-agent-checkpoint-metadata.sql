-- V12: 增强智能体 checkpoint 元数据与状态容量
ALTER TABLE `chat_session`
    MODIFY COLUMN `state_json` LONGTEXT DEFAULT NULL COMMENT 'StateGraph AgentState 序列化数据',
    ADD COLUMN `checkpoint_version` INT NOT NULL DEFAULT 0 COMMENT '智能体 checkpoint 版本号' AFTER `state_json`,
    ADD COLUMN `checkpoint_node` VARCHAR(64) DEFAULT NULL COMMENT '智能体 checkpoint 当前节点' AFTER `checkpoint_version`,
    ADD COLUMN `checkpoint_exit_reason` VARCHAR(64) DEFAULT NULL COMMENT '智能体 checkpoint 退出原因' AFTER `checkpoint_node`,
    ADD COLUMN `checkpoint_updated_at` DATETIME DEFAULT NULL COMMENT '智能体 checkpoint 更新时间' AFTER `checkpoint_exit_reason`;

CREATE INDEX `idx_chat_session_checkpoint_updated`
    ON `chat_session` (`checkpoint_updated_at` DESC);
