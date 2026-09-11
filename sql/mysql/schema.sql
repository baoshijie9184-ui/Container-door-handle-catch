SET NAMES utf8mb4;
SET CHARACTER SET utf8mb4;
SET character_set_connection = utf8mb4;
SET character_set_client = utf8mb4;
SET character_set_results = utf8mb4;

USE doorhandledb;

CREATE TABLE IF NOT EXISTS `operation_audit_log` (
    `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    `operator` VARCHAR(64) NOT NULL,
    `action` VARCHAR(32) NOT NULL,
    `resource_type` VARCHAR(64) NOT NULL,
    `resource_id` VARCHAR(128) DEFAULT NULL,
    `request_method` VARCHAR(16) DEFAULT NULL,
    `request_path` VARCHAR(512) DEFAULT NULL,
    `change_summary` JSON DEFAULT NULL,
    `result` VARCHAR(16) NOT NULL,
    `client_ip` VARCHAR(45) DEFAULT NULL,
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    KEY `idx_audit_operator_time` (`operator`, `created_at`),
    KEY `idx_audit_resource_time` (`resource_type`, `resource_id`, `created_at`),
    KEY `idx_audit_created_at` (`created_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

USE doorhandledb;

-- ============================================================
-- 用户表
-- ============================================================
CREATE TABLE IF NOT EXISTS users (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    username VARCHAR(50) NOT NULL UNIQUE,
    password VARCHAR(255) NOT NULL,
    email VARCHAR(100),
    phone VARCHAR(20),
    role VARCHAR(16) NOT NULL DEFAULT 'INSPECTOR',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ============================================================
-- 模型管理表（model_id 直接作为主键）
-- ============================================================
CREATE TABLE IF NOT EXISTS `model_management` (
    `model_id` INT NOT NULL COMMENT '模型唯一标识ID（主键）',
    `model_name` VARCHAR(100) NOT NULL COMMENT '模型名称',
    `version` VARCHAR(20) NOT NULL COMMENT '版本号',
    `model_path` VARCHAR(255) NOT NULL COMMENT '模型文件路径',
    `upload_time` DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '上传时间',
    `update_description` VARCHAR(500) DEFAULT NULL COMMENT '更新说明',
    `status` VARCHAR(32) NOT NULL DEFAULT 'READY' COMMENT '模型状态: DRAFT/READY/PUBLISHED/DISABLED/ARCHIVED',
    `is_default` TINYINT(1) NOT NULL DEFAULT 0 COMMENT '是否默认模型',
    `creator` VARCHAR(64) DEFAULT NULL COMMENT '上传人',
    `published_at` DATETIME DEFAULT NULL COMMENT '发布时间',
    `last_used_at` DATETIME DEFAULT NULL COMMENT '最近使用时间',
    `usage_count` INT NOT NULL DEFAULT 0 COMMENT '使用次数',
    `validation_status` VARCHAR(32) NOT NULL DEFAULT 'PENDING' COMMENT '校验状态: PENDING/PASSED/FAILED',
    `validation_message` VARCHAR(255) DEFAULT NULL COMMENT '校验说明',
    `mlops_status` VARCHAR(32) NOT NULL DEFAULT 'UNASSESSED' COMMENT 'MLOps状态: UNASSESSED/EVALUATED/ROLLOUT/ROLLED_BACK',
    `evaluation_dataset` VARCHAR(128) DEFAULT NULL COMMENT '评估测试集名称',
    `precision_score` DECIMAL(8,4) DEFAULT NULL COMMENT '精确率',
    `recall_score` DECIMAL(8,4) DEFAULT NULL COMMENT '召回率',
    `map_score` DECIMAL(8,4) DEFAULT NULL COMMENT 'mAP指标',
    `f1_score` DECIMAL(8,4) DEFAULT NULL COMMENT 'F1指标',
    `avg_inference_ms` INT DEFAULT NULL COMMENT '平均推理耗时毫秒',
    `compatibility_note` VARCHAR(500) DEFAULT NULL COMMENT '版本兼容性说明',
    `deployment_strategy` VARCHAR(32) NOT NULL DEFAULT 'FULL' COMMENT '部署策略: FULL/CANARY/AB_TEST/ROLLBACK',
    `canary_percent` INT NOT NULL DEFAULT 100 COMMENT '灰度流量比例',
    `ab_group` VARCHAR(32) DEFAULT NULL COMMENT 'A/B测试分组',
    `rollback_from_model_id` INT DEFAULT NULL COMMENT '回滚来源模型ID',
    PRIMARY KEY (`model_id`),
    UNIQUE KEY `uk_model_name_version` (`model_name`, `version`),
    KEY `idx_model_management_status_upload` (`status`, `upload_time` DESC),
    KEY `idx_model_management_default_status` (`is_default`, `status`),
    KEY `idx_model_management_validation_status` (`validation_status`),
    KEY `idx_model_management_mlops_status` (`mlops_status`),
    KEY `idx_model_management_deployment_strategy` (`deployment_strategy`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='ONNX模型管理表';

CREATE TABLE IF NOT EXISTS `model_operation_log` (
    `id` BIGINT NOT NULL AUTO_INCREMENT COMMENT '主键ID',
    `model_id` INT NOT NULL COMMENT '模型ID',
    `operation_type` VARCHAR(32) NOT NULL COMMENT '操作类型',
    `operator` VARCHAR(64) DEFAULT NULL COMMENT '操作人',
    `operation_time` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '操作时间',
    `remark` VARCHAR(255) DEFAULT NULL COMMENT '备注',
    PRIMARY KEY (`id`),
    KEY `idx_model_operation_log_model_id` (`model_id`),
    KEY `idx_model_operation_log_time` (`operation_time`),
    KEY `idx_model_operation_log_model_time` (`model_id`, `operation_time` DESC, `id` DESC),
    CONSTRAINT `fk_model_operation_log_model` FOREIGN KEY (`model_id`) REFERENCES `model_management` (`model_id`) ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='模型操作日志表';

INSERT INTO `model_management` (
    `model_id`, `model_name`, `version`, `model_path`, `upload_time`, `update_description`,
    `status`, `is_default`, `creator`, `published_at`, `last_used_at`, `usage_count`, `validation_status`, `validation_message`
)
SELECT seed.model_id, seed.model_name, seed.version, seed.model_path, seed.upload_time, seed.update_description
     , seed.status, seed.is_default, seed.creator, seed.published_at, seed.last_used_at, seed.usage_count, seed.validation_status, seed.validation_message
FROM (
    SELECT 1 AS model_id, 'YOLOv8' AS model_name, 'n' AS version, '/uploads/models/yolov8n_door_handle.onnx' AS model_path, '2025-06-01 10:00:00' AS upload_time, '轻量模型，适合快速检测' AS update_description,
           'READY' AS status, 0 AS is_default, 'system' AS creator, NULL AS published_at, NULL AS last_used_at, 0 AS usage_count, 'PASSED' AS validation_status, '基础校验通过' AS validation_message
    UNION ALL SELECT 2, 'YOLOv8', 's', '/uploads/models/yolov8s_door_handle.onnx', '2025-06-08 09:30:00', '平衡速度与准确率',
           'READY', 0, 'system', NULL, NULL, 0, 'PASSED', '基础校验通过'
    UNION ALL SELECT 3, 'YOLOv8', 'm', '/uploads/models/yolov8m_door_handle.onnx', '2025-06-15 14:30:00', '用于常规批量检测',
           'PUBLISHED', 1, 'system', '2025-06-15 14:45:00', NULL, 0, 'PASSED', '基础校验通过'
    UNION ALL SELECT 4, 'YOLOv8', 'l', '/uploads/models/yolov8l_door_handle.onnx', '2025-06-20 11:15:00', '高精度检测模型',
           'DISABLED', 0, 'system', '2025-06-20 11:30:00', NULL, 0, 'PASSED', '基础校验通过'
) AS seed
WHERE NOT EXISTS (SELECT 1 FROM `model_management` LIMIT 1);

-- image_detection_data 表已废弃，统一使用 detection_task 表存储所有检测结果
-- CREATE TABLE IF NOT EXISTS `image_detection_data` ( ... ) 已移除

-- ============================================================
-- 检测任务表
-- ============================================================
CREATE TABLE IF NOT EXISTS `detection_task` (
    `id` BIGINT NOT NULL AUTO_INCREMENT COMMENT '主键ID',
    `task_id` VARCHAR(64) NOT NULL COMMENT '任务编号',
    `workflow_uuid` VARCHAR(36) DEFAULT NULL COMMENT '工作流UUID，可在智能助手中引用',
    `task_type` VARCHAR(32) NOT NULL DEFAULT 'BATCH' COMMENT '任务类型',
    `batch_no` VARCHAR(128) DEFAULT NULL COMMENT '生产/采集批次号',
    `work_order_no` VARCHAR(128) DEFAULT NULL COMMENT '质检工单号',
    `flow_status` VARCHAR(32) DEFAULT NULL COMMENT '业务流转状态',
    `quality_station` VARCHAR(64) DEFAULT NULL COMMENT '质检工位/复核站点',
    `assignee` VARCHAR(64) DEFAULT NULL COMMENT '质检责任人',
    `assignment_remark` VARCHAR(500) DEFAULT NULL COMMENT '质检分派备注',
    `assigned_at` DATETIME DEFAULT NULL COMMENT '质检分派时间',
    `due_at` DATETIME DEFAULT NULL COMMENT '质检截止时间',
    `status` VARCHAR(32) NOT NULL COMMENT '任务状态',
    `stage` VARCHAR(32) DEFAULT NULL COMMENT '当前阶段',
    `dispatch_id` VARCHAR(64) DEFAULT NULL COMMENT '当前检测调度标识',
    `last_finished_event_id` VARCHAR(128) DEFAULT NULL COMMENT '最后处理的完成事件标识',
    `model_id` INT DEFAULT NULL COMMENT '模型ID（外键 -> model_management.model_id）',
    `model_version` VARCHAR(64) DEFAULT NULL COMMENT '模型版本',
    `threshold` DECIMAL(5,4) DEFAULT 0.5000 COMMENT '检测阈值',
    `capture_date` VARCHAR(32) DEFAULT NULL COMMENT '采集日期',
    `region` VARCHAR(64) DEFAULT NULL COMMENT '地区',
    `collector` VARCHAR(64) DEFAULT NULL COMMENT '采集员姓名（快照）',
    `device_name` VARCHAR(128) DEFAULT NULL COMMENT '采集设备名称（快照）',
    `image_folder_name` VARCHAR(128) DEFAULT NULL COMMENT '图片文件夹名称',
    `total_images` INT DEFAULT 0 COMMENT '总图片数',
    `processed_images` INT DEFAULT 0 COMMENT '已处理图片数',
    `successful_images` INT DEFAULT 0 COMMENT '成功图片数',
    `failed_images` INT DEFAULT 0 COMMENT '失败图片数',
    `source_oss_prefix` VARCHAR(255) DEFAULT NULL COMMENT '原图 OSS 前缀',
    `result_oss_prefix` VARCHAR(255) DEFAULT NULL COMMENT '结果 OSS 前缀',
    `result_json_oss_key` VARCHAR(255) DEFAULT NULL COMMENT '结果 JSON OSS Key',
    `original_image_keys_json` LONGTEXT DEFAULT NULL COMMENT '原图对象 key 列表 JSON',
    `preview_image_keys_json` LONGTEXT DEFAULT NULL COMMENT '预览图对象 key 列表 JSON',
    `statistics_json` LONGTEXT DEFAULT NULL COMMENT '统计结果 JSON',
    `defect_evidence_json` LONGTEXT DEFAULT NULL COMMENT '结构化缺陷证据 JSON，包含缺陷框/面积/置信度/位置/严重等级',
    `defect_count` INT NOT NULL DEFAULT 0 COMMENT '结构化缺陷数量',
    `primary_defect_type` VARCHAR(64) DEFAULT NULL COMMENT '主要缺陷类型',
    `max_defect_severity` VARCHAR(32) DEFAULT NULL COMMENT '最高缺陷严重等级: MINOR/MAJOR/CRITICAL',
    `error_message` VARCHAR(500) DEFAULT NULL COMMENT '错误信息',
    `review_status` VARCHAR(32) DEFAULT NULL COMMENT '复核状态: PENDING/REVIEWED',
    `review_conclusion` VARCHAR(64) DEFAULT NULL COMMENT '复核结论',
    `severity_level` VARCHAR(32) DEFAULT NULL COMMENT '严重等级',
    `confirmed_defect_count` INT DEFAULT 0 COMMENT '人工确认缺陷数',
    `false_positive_count` INT DEFAULT 0 COMMENT '误报数量',
    `review_remark` VARCHAR(1000) DEFAULT NULL COMMENT '复核备注',
    `reviewer` VARCHAR(64) DEFAULT NULL COMMENT '复核人',
    `reviewed_at` DATETIME DEFAULT NULL COMMENT '复核时间',
    `disposition_status` VARCHAR(32) DEFAULT NULL COMMENT '处置状态: PENDING/DISPOSED',
    `disposition_action` VARCHAR(32) DEFAULT NULL COMMENT '处置动作: RELEASE/REWORK/RECHECK/HOLD/SCRAP',
    `disposition_remark` VARCHAR(1000) DEFAULT NULL COMMENT '处置备注',
    `disposition_operator` VARCHAR(64) DEFAULT NULL COMMENT '处置人',
    `disposed_at` DATETIME DEFAULT NULL COMMENT '处置时间',
    `recheck_required` TINYINT(1) NOT NULL DEFAULT 0 COMMENT '是否需要复检',
    `rework_result` VARCHAR(64) DEFAULT NULL COMMENT '返工结果',
    `rework_operator` VARCHAR(64) DEFAULT NULL COMMENT '返工执行人',
    `rework_remark` VARCHAR(1000) DEFAULT NULL COMMENT '返工备注',
    `rework_completed_at` DATETIME DEFAULT NULL COMMENT '返工完成时间',
    `created_by` VARCHAR(64) DEFAULT NULL COMMENT '创建人用户名（外键 -> users.username）',
    `session_id` VARCHAR(64) DEFAULT NULL COMMENT '聊天会话ID（外键 -> chat_session.session_id）',
    `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    `started_at` DATETIME DEFAULT NULL COMMENT '开始时间',
    `finished_at` DATETIME DEFAULT NULL COMMENT '完成时间',
    `updated_at` DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    PRIMARY KEY (`id`),
    UNIQUE KEY `uk_detection_task_id` (`task_id`),
    UNIQUE KEY `uk_detection_task_workflow_uuid` (`workflow_uuid`),
    KEY `idx_detection_task_status` (`status`),
    KEY `idx_detection_task_batch_no` (`batch_no`),
    KEY `idx_detection_task_work_order_no` (`work_order_no`),
    KEY `idx_detection_task_flow_status` (`flow_status`),
    KEY `idx_detection_task_created_at` (`created_at`),
    KEY `idx_detection_task_model_id` (`model_id`),
    KEY `idx_detection_task_created_by` (`created_by`),
    KEY `idx_detection_task_status_created` (`status`, `created_at` DESC),
    KEY `idx_detection_task_collector_created` (`collector`, `created_at` DESC),
    KEY `idx_detection_task_device_created` (`device_name`, `created_at` DESC),
    KEY `idx_detection_task_region_created` (`region`, `created_at` DESC),
    KEY `idx_detection_task_review_time` (`review_status`, `reviewed_at` DESC),
    KEY `idx_detection_task_flow_created` (`flow_status`, `created_at` DESC),
    KEY `idx_detection_task_assignee_flow` (`assignee`, `flow_status`, `due_at`),
    KEY `idx_detection_task_quality_station` (`quality_station`, `flow_status`, `due_at`),
    KEY `idx_detection_task_due_at` (`due_at`),
    KEY `idx_detection_task_disposition_status` (`disposition_status`),
    KEY `idx_detection_task_disposed_at` (`disposed_at`),
    KEY `idx_detection_task_disposition_action` (`disposition_action`),
    KEY `idx_detection_task_primary_defect` (`primary_defect_type`, `created_at` DESC),
    KEY `idx_detection_task_severity_created` (`max_defect_severity`, `created_at` DESC),
    KEY `idx_detection_task_device_defect` (`device_name`, `primary_defect_type`, `created_at` DESC),
    KEY `idx_detection_task_creator_created` (`created_by`, `created_at` DESC),
    CONSTRAINT `fk_detection_task_model` FOREIGN KEY (`model_id`) REFERENCES `model_management` (`model_id`) ON DELETE SET NULL ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='OSS 检测任务表';

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

-- ============================================================
-- 聊天会话表（外键关联 users 表）
-- ============================================================
CREATE TABLE IF NOT EXISTS `chat_session` (
    `id` BIGINT NOT NULL AUTO_INCREMENT COMMENT '主键ID',
    `session_id` VARCHAR(64) NOT NULL COMMENT '会话编号',
    `username` VARCHAR(64) NOT NULL COMMENT '用户名（外键 -> users.username）',
    `user_id` BIGINT NOT NULL COMMENT '不可变用户租户ID（外键 -> users.id）',
    `title` VARCHAR(255) DEFAULT NULL COMMENT '会话标题',
    `status` VARCHAR(32) NOT NULL DEFAULT 'ACTIVE' COMMENT '会话状态',
    `pinned` TINYINT(1) DEFAULT 0 COMMENT '是否置顶',
    `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    `updated_at` DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    `state_json` LONGTEXT DEFAULT NULL COMMENT 'StateGraph AgentState 序列化数据',
    `checkpoint_version` INT NOT NULL DEFAULT 0 COMMENT '智能体 checkpoint 版本号',
    `checkpoint_node` VARCHAR(64) DEFAULT NULL COMMENT '智能体 checkpoint 当前节点',
    `checkpoint_exit_reason` VARCHAR(64) DEFAULT NULL COMMENT '智能体 checkpoint 退出原因',
    `checkpoint_updated_at` DATETIME DEFAULT NULL COMMENT '智能体 checkpoint 更新时间',
    PRIMARY KEY (`id`),
    UNIQUE KEY `uk_chat_session_id` (`session_id`),
    KEY `idx_chat_session_username` (`username`),
    KEY `idx_chat_session_status` (`status`),
    KEY `idx_chat_session_pinned_updated` (`pinned` DESC, `updated_at` DESC),
    KEY `idx_chat_session_user_status_updated` (`username`, `status`, `updated_at` DESC),
    KEY `idx_chat_session_user_status_pinned_updated` (`username`, `status`, `pinned` DESC, `updated_at` DESC),
    KEY `idx_chat_session_tenant_status_updated` (`user_id`, `status`, `updated_at` DESC),
    KEY `idx_chat_session_tenant_status_pinned_updated` (`user_id`, `status`, `pinned` DESC, `updated_at` DESC),
    KEY `idx_chat_session_checkpoint_updated` (`checkpoint_updated_at` DESC),
    CONSTRAINT `fk_chat_session_user` FOREIGN KEY (`username`) REFERENCES `users` (`username`) ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT `fk_chat_session_tenant_user` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE CASCADE ON UPDATE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='聊天会话表';

-- ============================================================
-- 聊天消息表（外键关联 chat_session 表）
-- ============================================================
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

-- ============================================================
-- 聊天待确认动作表（外键关联 chat_session 表）
-- ============================================================
CREATE TABLE IF NOT EXISTS `chat_pending_action` (
    `id` BIGINT NOT NULL AUTO_INCREMENT COMMENT '主键ID',
    `action_id` VARCHAR(64) NOT NULL COMMENT '动作编号',
    `session_id` VARCHAR(64) NOT NULL COMMENT '会话编号（外键 -> chat_session.session_id）',
    `action_type` VARCHAR(64) NOT NULL COMMENT '动作类型',
    `action_payload_json` LONGTEXT NOT NULL COMMENT '动作载荷',
    `status` VARCHAR(32) NOT NULL DEFAULT 'PENDING' COMMENT '动作状态',
    `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    `confirmed_at` DATETIME DEFAULT NULL COMMENT '确认时间',
    `error_message` VARCHAR(500) DEFAULT NULL COMMENT '动作失败摘要',
    PRIMARY KEY (`id`),
    UNIQUE KEY `uk_chat_pending_action_id` (`action_id`),
    KEY `idx_chat_pending_session_id` (`session_id`),
    KEY `idx_chat_pending_session_status_created` (`session_id`, `status`, `created_at` DESC),
    CONSTRAINT `fk_chat_pending_session` FOREIGN KEY (`session_id`) REFERENCES `chat_session` (`session_id`) ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='聊天待确认动作表';

-- 检测结果现在统一使用 detection_task 表

-- ============================================================
-- 员工表
-- ============================================================
CREATE TABLE IF NOT EXISTS `employee` (
    `id` BIGINT NOT NULL AUTO_INCREMENT COMMENT '主键ID',
    `name` VARCHAR(50) NOT NULL COMMENT '姓名',
    `employee_number` VARCHAR(50) NOT NULL COMMENT '员工编号',
    `contact` VARCHAR(50) NOT NULL COMMENT '联系方式',
    `department` VARCHAR(100) NOT NULL COMMENT '所属部门',
    `employee_type` VARCHAR(50) NOT NULL COMMENT '人员类型: DETECTION/COLLECTION/MAINTENANCE',
    `gender` VARCHAR(10) NOT NULL COMMENT '性别',
    `id_card` VARCHAR(18) DEFAULT NULL COMMENT '身份证号',
    `hire_date` DATE NOT NULL COMMENT '入职日期',
    `status` VARCHAR(20) NOT NULL COMMENT '状态: ACTIVE/RESIGNED/VACATION',
    `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    `updated_at` DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    `version` INT NOT NULL DEFAULT 0 COMMENT '乐观锁版本',
    PRIMARY KEY (`id`),
    UNIQUE KEY `uk_employee_number` (`employee_number`),
    UNIQUE KEY `uk_id_card` (`id_card`),
    KEY `idx_employee_type` (`employee_type`),
    KEY `idx_employee_department` (`department`),
    KEY `idx_employee_status` (`status`),
    KEY `idx_employee_type_status` (`employee_type`, `status`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='员工表';

INSERT INTO `employee` (
    `id`, `name`, `employee_number`, `contact`, `department`, `employee_type`,
    `gender`, `id_card`, `hire_date`, `status`
)
SELECT seed.id, seed.name, seed.employee_number, seed.contact, seed.department, seed.employee_type,
       seed.gender, seed.id_card, seed.hire_date, seed.status
FROM (
    SELECT 1 AS id, '张三' AS name, 'EMP-0001' AS employee_number, '13800138001' AS contact, '检测部一组' AS department, 'DETECTION' AS employee_type, '男' AS gender, '110101199001011234' AS id_card, '2024-01-15' AS hire_date, 'ACTIVE' AS status
    UNION ALL SELECT 2, '李四', 'EMP-0002', '13800138002', '采集部一组', 'COLLECTION', '男', '110101199102022345', '2024-02-20', 'ACTIVE'
    UNION ALL SELECT 3, '王五', 'EMP-0003', '13800138003', '维修部', 'MAINTENANCE', '男', '110101199203033456', '2024-03-10', 'ACTIVE'
    UNION ALL SELECT 4, '赵六', 'EMP-0004', '13800138004', '检测部二组', 'DETECTION', '女', '110101199304044567', '2024-01-05', 'ACTIVE'
    UNION ALL SELECT 5, '钱七', 'EMP-0005', '13800138005', '采集部二组', 'COLLECTION', '女', '110101199405055678', '2023-12-20', 'RESIGNED'
    UNION ALL SELECT 6, '孙八', 'EMP-0006', '13800138006', '维修部', 'MAINTENANCE', '男', '110101199506066789', '2024-02-01', 'ACTIVE'
    UNION ALL SELECT 7, '周九', 'EMP-0007', '13800138007', '检测部一组', 'DETECTION', '男', '110101199607077890', '2024-04-01', 'VACATION'
    UNION ALL SELECT 8, '吴十', 'EMP-0008', '13800138008', '采集部一组', 'COLLECTION', '女', '110101199708088901', '2024-04-18', 'ACTIVE'
    UNION ALL SELECT 9, '郑十一', 'EMP-0009', '13800138009', '检测部二组', 'DETECTION', '男', '110101199809099012', '2024-05-12', 'ACTIVE'
    UNION ALL SELECT 10, '冯十二', 'EMP-0010', '13800138010', '维修部', 'MAINTENANCE', '女', '110101199910100123', '2024-05-20', 'ACTIVE'
) AS seed
WHERE NOT EXISTS (SELECT 1 FROM `employee` LIMIT 1);

-- ============================================================
-- 设备管理表
-- 状态值: IN_USE-使用中, MAINTENANCE-维护中, IDLE-未使用, OFFLINE-离线
-- ============================================================
CREATE TABLE IF NOT EXISTS `device_management` (
    `id` BIGINT NOT NULL AUTO_INCREMENT COMMENT '主键ID',
    `device_code` VARCHAR(50) NOT NULL COMMENT '设备编号',
    `device_type` VARCHAR(50) NOT NULL COMMENT '设备类型',
    `model_name` VARCHAR(100) NOT NULL COMMENT '设备型号',
    `serial_number` VARCHAR(100) NOT NULL COMMENT '序列号',
    `status` VARCHAR(20) NOT NULL COMMENT '设备状态: IN_USE/MAINTENANCE/IDLE/OFFLINE',
    `online_status` VARCHAR(32) NOT NULL DEFAULT 'OFFLINE' COMMENT '在线状态: ONLINE/OFFLINE',
    `last_heartbeat_at` DATETIME DEFAULT NULL COMMENT '最近心跳时间',
    `station_code` VARCHAR(64) DEFAULT NULL COMMENT '产线工位编号',
    `edge_node_id` VARCHAR(64) DEFAULT NULL COMMENT '边缘工控节点编号',
    `plc_status` VARCHAR(32) DEFAULT NULL COMMENT 'PLC状态',
    `camera_status` VARCHAR(32) DEFAULT NULL COMMENT '相机状态',
    `capture_status` VARCHAR(32) DEFAULT NULL COMMENT '采集状态',
    `last_image_key` VARCHAR(255) DEFAULT NULL COMMENT '最近采集图片OSS Key',
    `last_capture_at` DATETIME DEFAULT NULL COMMENT '最近采集时间',
    `runtime_metadata_json` LONGTEXT DEFAULT NULL COMMENT '设备运行态扩展元数据JSON',
    `last_maintenance_date` DATETIME DEFAULT NULL COMMENT '最后维护时间',
    `employee_id` BIGINT DEFAULT NULL COMMENT '当前使用员工ID（外键 -> employee.id）',
    `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    `updated_at` DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    `version` INT NOT NULL DEFAULT 0 COMMENT '乐观锁版本',
    PRIMARY KEY (`id`),
    UNIQUE KEY `uk_device_code` (`device_code`),
    UNIQUE KEY `uk_serial_number` (`serial_number`),
    KEY `idx_employee_id` (`employee_id`),
    KEY `idx_device_status` (`status`),
    KEY `idx_device_type` (`device_type`),
    KEY `idx_device_type_status` (`device_type`, `status`),
    KEY `idx_device_online_heartbeat` (`online_status`, `last_heartbeat_at` DESC),
    KEY `idx_device_station_online` (`station_code`, `online_status`, `last_heartbeat_at` DESC),
    KEY `idx_device_edge_node` (`edge_node_id`),
    CONSTRAINT `fk_device_employee` FOREIGN KEY (`employee_id`) REFERENCES `employee` (`id`) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='设备管理表';

INSERT INTO `device_management` (
    `id`, `device_code`, `device_type`, `model_name`, `serial_number`,
    `status`, `last_maintenance_date`, `employee_id`
)
SELECT seed.id, seed.device_code, seed.device_type, seed.model_name, seed.serial_number,
       seed.status, seed.last_maintenance_date, seed.employee_id
FROM (
    SELECT 1 AS id, 'DEV-0001' AS device_code, 'DETECTION' AS device_type, 'Model-D400' AS model_name, 'SN-DET-0001' AS serial_number, 'IN_USE' AS status, '2025-06-10 09:00:00' AS last_maintenance_date, 1 AS employee_id
    UNION ALL SELECT 2, 'DEV-0002', 'IMAGE_CAPTURE', 'Model-C300', 'SN-CAP-0002', 'IN_USE', '2025-06-11 10:30:00', 2
    UNION ALL SELECT 3, 'DEV-0003', 'DETECTION', 'Model-D420', 'SN-DET-0003', 'MAINTENANCE', '2025-06-12 14:00:00', 3
    UNION ALL SELECT 4, 'DEV-0004', 'IMAGE_CAPTURE', 'Model-C320', 'SN-CAP-0004', 'IDLE', NULL, NULL
    UNION ALL SELECT 5, 'DEV-0005', 'DETECTION', 'Model-D450', 'SN-DET-0005', 'IN_USE', '2025-06-13 08:20:00', 4
    UNION ALL SELECT 6, 'DEV-0006', 'IMAGE_CAPTURE', 'Model-C350', 'SN-CAP-0006', 'OFFLINE', '2025-06-01 17:00:00', NULL
    UNION ALL SELECT 7, 'DEV-0007', 'IMAGE_CAPTURE', 'Model-C360', 'SN-CAP-0007', 'IN_USE', '2025-06-14 11:10:00', 8
    UNION ALL SELECT 8, 'DEV-0008', 'DETECTION', 'Model-D460', 'SN-DET-0008', 'IN_USE', '2025-06-15 15:20:00', 9
    UNION ALL SELECT 9, 'DEV-0009', 'DETECTION', 'Model-D470', 'SN-DET-0009', 'MAINTENANCE', '2025-06-16 09:45:00', 10
) AS seed
WHERE NOT EXISTS (SELECT 1 FROM `device_management` LIMIT 1);

CREATE TABLE IF NOT EXISTS `device_capture_alert` (
    `id` BIGINT NOT NULL AUTO_INCREMENT COMMENT '主键ID',
    `alert_id` VARCHAR(64) NOT NULL COMMENT '告警编号',
    `device_id` BIGINT DEFAULT NULL COMMENT '设备ID',
    `device_code` VARCHAR(50) NOT NULL COMMENT '设备编号快照',
    `device_type` VARCHAR(50) DEFAULT NULL COMMENT '设备类型快照',
    `station_code` VARCHAR(64) DEFAULT NULL COMMENT '产线工位编号',
    `edge_node_id` VARCHAR(64) DEFAULT NULL COMMENT '边缘工控节点编号',
    `alert_type` VARCHAR(64) NOT NULL COMMENT '告警类型: CAPTURE_EXCEPTION/HEARTBEAT_OFFLINE',
    `alert_level` VARCHAR(32) NOT NULL DEFAULT 'MAJOR' COMMENT '告警等级: MINOR/MAJOR/CRITICAL',
    `alert_message` VARCHAR(500) NOT NULL COMMENT '告警说明',
    `runtime_snapshot_json` LONGTEXT DEFAULT NULL COMMENT '告警发生时运行态快照JSON',
    `status` VARCHAR(32) NOT NULL DEFAULT 'OPEN' COMMENT '状态: OPEN/ACKNOWLEDGED/RESOLVED',
    `ack_operator` VARCHAR(64) DEFAULT NULL COMMENT '确认人',
    `ack_remark` VARCHAR(500) DEFAULT NULL COMMENT '确认备注',
    `acknowledged_at` DATETIME DEFAULT NULL COMMENT '确认时间',
    `resolved_operator` VARCHAR(64) DEFAULT NULL COMMENT '关闭人',
    `resolved_remark` VARCHAR(500) DEFAULT NULL COMMENT '关闭备注',
    `resolved_at` DATETIME DEFAULT NULL COMMENT '关闭时间',
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    PRIMARY KEY (`id`),
    UNIQUE KEY `uk_device_capture_alert_id` (`alert_id`),
    KEY `idx_capture_alert_status_created` (`status`, `created_at` DESC),
    KEY `idx_capture_alert_device_created` (`device_code`, `created_at` DESC),
    KEY `idx_capture_alert_level_created` (`alert_level`, `created_at` DESC),
    KEY `idx_capture_alert_station_status` (`station_code`, `status`, `created_at` DESC),
    CONSTRAINT `fk_capture_alert_device` FOREIGN KEY (`device_id`) REFERENCES `device_management` (`id`) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='采集端异常告警表';

-- ============================================================
-- 设备使用记录表
-- 状态值: IN_USE-使用中, RETURNED-已归还
-- 设备/员工信息字段为历史快照，保留创建时的数据
-- ============================================================
CREATE TABLE IF NOT EXISTS `device_usage_record` (
    `id` BIGINT NOT NULL AUTO_INCREMENT COMMENT '主键ID',
    `device_id` BIGINT NOT NULL COMMENT '设备ID（外键 -> device_management.id）',
    `device_code` VARCHAR(50) NOT NULL COMMENT '设备编号（快照）',
    `device_type` VARCHAR(50) NOT NULL COMMENT '设备类型（快照）',
    `model_name` VARCHAR(100) NOT NULL COMMENT '设备型号（快照）',
    `serial_number` VARCHAR(100) NOT NULL COMMENT '序列号（快照）',
    `employee_id` BIGINT NOT NULL COMMENT '员工ID（外键 -> employee.id）',
    `employee_name` VARCHAR(50) NOT NULL COMMENT '员工姓名（快照）',
    `employee_number` VARCHAR(50) NOT NULL COMMENT '员工编号（快照）',
    `contact` VARCHAR(50) NOT NULL COMMENT '联系方式（快照）',
    `start_time` DATETIME NOT NULL COMMENT '使用开始时间',
    `end_time` DATETIME DEFAULT NULL COMMENT '使用结束时间',
    `status` VARCHAR(20) NOT NULL DEFAULT 'IN_USE' COMMENT '记录状态: IN_USE/RETURNED',
    `remarks` VARCHAR(255) DEFAULT NULL COMMENT '备注',
    `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    `updated_at` DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    PRIMARY KEY (`id`),
    KEY `idx_device_id` (`device_id`),
    KEY `idx_employee_id` (`employee_id`),
    KEY `idx_start_time` (`start_time`),
    KEY `idx_end_time` (`end_time`),
    KEY `idx_status` (`status`),
    KEY `idx_usage_device_start` (`device_id`, `start_time` DESC),
    KEY `idx_usage_employee_start` (`employee_id`, `start_time` DESC),
    KEY `idx_usage_status_start` (`status`, `start_time` DESC),
    KEY `idx_usage_active_device` (`device_id`, `status`, `end_time`, `start_time` DESC),
    CONSTRAINT `fk_usage_device` FOREIGN KEY (`device_id`) REFERENCES `device_management` (`id`) ON DELETE CASCADE,
    CONSTRAINT `fk_usage_employee` FOREIGN KEY (`employee_id`) REFERENCES `employee` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='设备使用记录表';

INSERT INTO `device_usage_record` (
    `id`, `device_id`, `device_code`, `device_type`, `model_name`, `serial_number`,
    `employee_id`, `employee_name`, `employee_number`, `contact`,
    `start_time`, `end_time`, `status`, `remarks`
)
SELECT seed.id, seed.device_id, seed.device_code, seed.device_type, seed.model_name, seed.serial_number,
       seed.employee_id, seed.employee_name, seed.employee_number, seed.contact,
       seed.start_time, seed.end_time, seed.status, seed.remarks
FROM (
    SELECT 1 AS id, 1 AS device_id, 'DEV-0001' AS device_code, 'DETECTION' AS device_type, 'Model-D400' AS model_name, 'SN-DET-0001' AS serial_number,
           1 AS employee_id, '张三' AS employee_name, 'EMP-0001' AS employee_number, '13800138001' AS contact,
           '2025-06-18 08:00:00' AS start_time, '2025-06-18 17:30:00' AS end_time, 'RETURNED' AS status, '检测任务 A 班次' AS remarks
    UNION ALL
    SELECT 2, 2, 'DEV-0002', 'IMAGE_CAPTURE', 'Model-C300', 'SN-CAP-0002',
           2, '李四', 'EMP-0002', '13800138002',
           '2025-06-18 08:30:00', '2025-06-18 18:00:00', 'RETURNED', '采集任务 A 班次'
    UNION ALL
    SELECT 3, 3, 'DEV-0003', 'DETECTION', 'Model-D420', 'SN-DET-0003',
           3, '王五', 'EMP-0003', '13800138003',
           '2025-06-19 09:00:00', '2025-06-19 12:00:00', 'RETURNED', '维护巡检'
    UNION ALL
    SELECT 4, 5, 'DEV-0005', 'DETECTION', 'Model-D450', 'SN-DET-0005',
           4, '赵六', 'EMP-0004', '13800138004',
           '2025-06-20 08:10:00', '2025-06-20 17:40:00', 'RETURNED', '检测任务 B 班次'
    UNION ALL
    SELECT 5, 7, 'DEV-0007', 'IMAGE_CAPTURE', 'Model-C360', 'SN-CAP-0007',
           8, '吴十', 'EMP-0008', '13800138008',
           '2025-06-20 09:20:00', '2025-06-20 18:10:00', 'RETURNED', '采集任务 B 班次'
    UNION ALL
    SELECT 6, 8, 'DEV-0008', 'DETECTION', 'Model-D460', 'SN-DET-0008',
           9, '郑十一', 'EMP-0009', '13800138009',
           '2025-06-21 08:00:00', '2025-06-21 17:00:00', 'RETURNED', '检测任务 C 班次'
    UNION ALL
    SELECT 7, 9, 'DEV-0009', 'DETECTION', 'Model-D470', 'SN-DET-0009',
           10, '冯十二', 'EMP-0010', '13800138010',
           '2025-06-21 13:00:00', '2025-06-21 16:20:00', 'RETURNED', '维护校准'
    UNION ALL
    SELECT 8, 1, 'DEV-0001', 'DETECTION', 'Model-D400', 'SN-DET-0001',
           1, '张三', 'EMP-0001', '13800138001',
           '2025-06-22 08:05:00', NULL, 'IN_USE', '当前检测任务'
    UNION ALL
    SELECT 9, 2, 'DEV-0002', 'IMAGE_CAPTURE', 'Model-C300', 'SN-CAP-0002',
           2, '李四', 'EMP-0002', '13800138002',
           '2025-06-22 08:20:00', NULL, 'IN_USE', '当前采集任务'
    UNION ALL
    SELECT 10, 3, 'DEV-0003', 'DETECTION', 'Model-D420', 'SN-DET-0003',
           3, '王五', 'EMP-0003', '13800138003',
           '2025-06-22 09:15:00', NULL, 'IN_USE', '当前维护任务'
    UNION ALL
    SELECT 11, 5, 'DEV-0005', 'DETECTION', 'Model-D450', 'SN-DET-0005',
           4, '赵六', 'EMP-0004', '13800138004',
           '2025-06-23 08:00:00', NULL, 'IN_USE', '复检任务'
    UNION ALL
    SELECT 12, 7, 'DEV-0007', 'IMAGE_CAPTURE', 'Model-C360', 'SN-CAP-0007',
           8, '吴十', 'EMP-0008', '13800138008',
           '2025-06-23 09:00:00', NULL, 'IN_USE', '补采任务'
) AS seed
WHERE NOT EXISTS (SELECT 1 FROM `device_usage_record` LIMIT 1);

-- ============================================================
-- 添加延迟外键约束（需在所有表创建完成后执行）
-- ============================================================

-- detection_task.session_id -> chat_session.session_id
ALTER TABLE `detection_task`
    ADD CONSTRAINT `fk_detection_task_session`
    FOREIGN KEY (`session_id`) REFERENCES `chat_session` (`session_id`)
    ON DELETE SET NULL ON UPDATE CASCADE;
