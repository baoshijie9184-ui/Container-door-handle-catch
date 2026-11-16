-- Source DDL only. Create the referenced users fixture first.
CREATE TABLE IF NOT EXISTS `chat_project` (
    `id` BIGINT NOT NULL AUTO_INCREMENT,
    `project_id` VARCHAR(64) NOT NULL,
    `username` VARCHAR(64) NOT NULL,
    `user_id` BIGINT NOT NULL,
    `name` VARCHAR(100) NOT NULL,
    `description` VARCHAR(500) DEFAULT NULL,
    `color` VARCHAR(20) DEFAULT '#4f6ef7',
    `sort_order` INT DEFAULT 0,
    `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
    `updated_at` DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    UNIQUE KEY `uk_chat_project_id` (`project_id`),
    KEY `idx_chat_project_username` (`username`),
    KEY `idx_chat_project_tenant_sort_created` (`user_id`, `sort_order`, `created_at` DESC),
    CONSTRAINT `fk_chat_project_user` FOREIGN KEY (`username`) REFERENCES `users` (`username`) ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT `fk_chat_project_tenant_user` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE CASCADE ON UPDATE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='聊天项目表';

CREATE TABLE `chat_session` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `session_id` varchar(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `username` varchar(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `user_id` bigint NOT NULL,
  `title` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `status` varchar(32) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'ACTIVE',
  `pinned` tinyint(1) DEFAULT '0' COMMENT '是否置顶',
  `project_id` varchar(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '鎵?睘椤圭洰ID',
  `created_at` datetime DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  `state_json` longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci COMMENT 'StateGraph AgentState 序列化数据',
  `checkpoint_version` int NOT NULL DEFAULT '0' COMMENT '智能体 checkpoint 版本号',
  `checkpoint_node` varchar(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '智能体 checkpoint 当前节点',
  `checkpoint_exit_reason` varchar(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '智能体 checkpoint 退出原因',
  `checkpoint_updated_at` datetime DEFAULT NULL COMMENT '智能体 checkpoint 更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_chat_session_id` (`session_id`),
  KEY `idx_chat_session_username` (`username`),
  KEY `idx_chat_session_project` (`project_id`),
  KEY `idx_chat_session_checkpoint_updated` (`checkpoint_updated_at` DESC),
  KEY `idx_chat_session_tenant_status_updated` (`user_id`,`status`,`updated_at` DESC),
  KEY `idx_chat_session_tenant_status_pinned_updated` (`user_id`,`status`,`pinned` DESC,`updated_at` DESC),
  CONSTRAINT `fk_chat_session_tenant_user` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE CASCADE ON UPDATE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `chat_message` (
    `id` BIGINT NOT NULL AUTO_INCREMENT COMMENT '主键ID',
    `session_id` VARCHAR(64) NOT NULL COMMENT '会话编号（外键 -> chat_session.session_id）',
    `role` VARCHAR(16) NOT NULL COMMENT '消息角色',
    `message_type` VARCHAR(32) NOT NULL DEFAULT 'TEXT' COMMENT '消息类型',
    `content` LONGTEXT NOT NULL COMMENT '消息内容',
    `intent` VARCHAR(64) DEFAULT NULL COMMENT '识别意图',
    `action_id` VARCHAR(64) DEFAULT NULL COMMENT '待确认动作ID',
    `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    PRIMARY KEY (`id`),
    KEY `idx_chat_message_session_id` (`session_id`),
    KEY `idx_chat_message_session_created` (`session_id`, `id`),
    CONSTRAINT `fk_chat_message_session` FOREIGN KEY (`session_id`) REFERENCES `chat_session` (`session_id`) ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='聊天消息表';

CREATE TABLE IF NOT EXISTS detection_image_fingerprint (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    sha256 CHAR(64) NOT NULL,
    file_name VARCHAR(255) NOT NULL,
    object_key VARCHAR(512) NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'NEW',
    last_task_id VARCHAR(64) NULL,
    owner_user_id VARCHAR(64) NULL,
    version INT NOT NULL DEFAULT 0,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_detection_image_sha256 (sha256),
    KEY idx_detection_image_status (status),
    KEY idx_detection_image_owner (owner_user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='检测图片指纹与最近检测状态';

CREATE TABLE IF NOT EXISTS agent_research_storage_owner (
  user_id BIGINT NOT NULL,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE TABLE IF NOT EXISTS agent_skill_download_owner (
 owner_user_id BIGINT NOT NULL PRIMARY KEY
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
