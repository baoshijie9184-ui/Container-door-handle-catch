# MySQL 数据库表结构与业务关系详解

## 一、数据库概述

项目使用 MySQL/InnoDB，数据库名为 `doorhandledb`，字符集统一为 `utf8mb4`，排序规则为 `utf8mb4_unicode_ci`。当前最终结构以 `src/main/resources/db/schema.sql` 为准，共包含 11 张核心业务表。

| 业务域 | 数据表 | 用途 |
| --- | --- | --- |
| 用户认证 | `users` | 登录账号、角色和联系方式 |
| Hermes Agent | `chat_session`、`chat_message`、`chat_pending_action` | 会话、消息、Checkpoint、确认动作 |
| 检测质量 | `detection_task` | 检测任务、Kafka 调度、结果、复核、处置、返工 |
| 模型治理 | `model_management`、`model_operation_log` | ONNX 模型生命周期和操作审计 |
| 员工设备 | `employee`、`device_management`、`device_capture_alert`、`device_usage_record` | 人员、设备、告警和使用历史 |

> `image_detection_data` 已废弃，单图和批量检测结果统一存入 `detection_task`。

## 二、整体 ER 关系

```text
users(username)
  └─1:N─ chat_session(username)
           ├─1:N─ chat_message(session_id)
           ├─1:N─ chat_pending_action(session_id)
           └─1:N─ detection_task(session_id，删除会话后置 NULL)

model_management(model_id)
  ├─1:N─ model_operation_log(model_id，级联删除)
  └─1:N─ detection_task(model_id，删除模型后置 NULL)

employee(id)
  ├─1:N─ device_management(employee_id，删除员工后置 NULL)
  └─1:N─ device_usage_record(employee_id，级联删除)

device_management(id)
  ├─1:N─ device_capture_alert(device_id，删除设备后置 NULL)
  └─1:N─ device_usage_record(device_id，级联删除)
```

`detection_task.created_by` 与 `users.username` 在注释和业务代码中存在逻辑关系，但当前最终 Schema 未建立该外键。`collector`、`device_name`、使用记录中的人员/设备文本字段属于历史快照，不应作为强外键理解。

## 三、用户认证域

### 3.1 `users` 用户表

用途：保存系统登录账号、BCrypt 密码摘要、联系方式和角色。`username` 同时作为 Agent 会话的业务外键。

| 字段名 | MySQL 类型 | 可空 | 默认值 | 键/属性 | 业务含义 |
| --- | --- | --- | --- | --- | --- |
| `id` | BIGINT | 否 | 自增 | PK | 用户内部主键 |
| `username` | VARCHAR(50) | 否 | 无 | UNIQUE | 登录名、业务关联键 |
| `password` | VARCHAR(255) | 否 | 无 |  | BCrypt 密码摘要 |
| `email` | VARCHAR(100) | 是 | NULL |  | 邮箱 |
| `phone` | VARCHAR(20) | 是 | NULL |  | 手机号 |
| `role` | VARCHAR(16) | 否 | `OPERATOR` |  | `ADMIN`/`OPERATOR` |
| `created_at` | DATETIME | 是 | CURRENT_TIMESTAMP |  | 创建时间 |
| `updated_at` | DATETIME | 是 | CURRENT_TIMESTAMP | ON UPDATE | 更新时间 |

设计说明：使用自增 BIGINT 作为聚簇主键，写入局部性好；用户名唯一索引既保证登录名唯一，也支撑 `chat_session` 外键。

## 四、Hermes Agent 会话域

### 4.1 `chat_session` 会话与 Checkpoint 表

用途：保存会话元数据及 StateGraph 状态快照，使请求被不同 Spring Boot 实例处理时仍能恢复 Agent 工作流。

| 字段名 | 类型 | 可空 | 默认值 | 键/索引 | 业务含义 |
| --- | --- | --- | --- | --- | --- |
| `id` | BIGINT | 否 | 自增 | PK | 内部主键 |
| `session_id` | VARCHAR(64) | 否 | 无 | UNIQUE | 对外会话编号 |
| `username` | VARCHAR(64) | 否 | 无 | FK、INDEX | 会话所有者 |
| `title` | VARCHAR(255) | 是 | NULL |  | 会话标题 |
| `status` | VARCHAR(32) | 否 | `ACTIVE` | INDEX | `ACTIVE`/`ARCHIVED` |
| `pinned` | TINYINT(1) | 是 | 0 | INDEX | 是否置顶 |
| `created_at` | DATETIME | 是 | CURRENT_TIMESTAMP |  | 创建时间 |
| `updated_at` | DATETIME | 是 | CURRENT_TIMESTAMP | ON UPDATE | 最近活动时间 |
| `state_json` | LONGTEXT | 是 | NULL |  | AgentState 应用层 JSON |
| `checkpoint_version` | INT | 否 | 0 |  | Checkpoint 版本 |
| `checkpoint_node` | VARCHAR(64) | 是 | NULL |  | 当前节点 |
| `checkpoint_exit_reason` | VARCHAR(64) | 是 | NULL |  | 退出/暂停原因 |
| `checkpoint_updated_at` | DATETIME | 是 | NULL | INDEX | 快照更新时间 |

外键：`username → users.username`，`ON DELETE CASCADE ON UPDATE CASCADE`。

关键复合索引：

- `(username, status, updated_at DESC)`：查询用户最近活跃会话。
- `(username, status, pinned DESC, updated_at DESC)`：会话侧栏置顶排序。
- `(checkpoint_updated_at DESC)`：Checkpoint 运行诊断。

### 4.2 `chat_message` 聊天消息表

| 字段名 | 类型 | 可空 | 默认值 | 键/索引 | 业务含义 |
| --- | --- | --- | --- | --- | --- |
| `id` | BIGINT | 否 | 自增 | PK | 消息顺序主键 |
| `session_id` | VARCHAR(64) | 否 | 无 | FK、INDEX | 所属会话 |
| `role` | VARCHAR(16) | 否 | 无 |  | `user`/`assistant` |
| `message_type` | VARCHAR(32) | 否 | `TEXT` |  | 文本、卡片或确认消息类型 |
| `content` | LONGTEXT | 否 | 无 |  | 消息正文 |
| `intent` | VARCHAR(64) | 是 | NULL |  | Agent 识别意图 |
| `action_id` | VARCHAR(64) | 是 | NULL |  | 关联待确认动作 |
| `created_at` | DATETIME | 是 | CURRENT_TIMESTAMP |  | 创建时间 |

外键：`session_id → chat_session.session_id`，删除会话时级联删除消息。索引 `(session_id, id)` 支撑按会话顺序读取和截取最近消息。

### 4.3 `chat_pending_action` 待确认动作表

| 字段名 | 类型 | 可空 | 默认值 | 键/索引 | 业务含义 |
| --- | --- | --- | --- | --- | --- |
| `id` | BIGINT | 否 | 自增 | PK | 内部主键 |
| `action_id` | VARCHAR(64) | 否 | 无 | UNIQUE | 动作编号 |
| `session_id` | VARCHAR(64) | 否 | 无 | FK、INDEX | 所属会话 |
| `action_type` | VARCHAR(64) | 否 | 无 |  | 动作类型 |
| `action_payload_json` | LONGTEXT | 否 | 无 |  | 动作参数应用层 JSON |
| `status` | VARCHAR(32) | 否 | `PENDING` | 复合索引 | 动作状态 |
| `created_at` | DATETIME | 是 | CURRENT_TIMESTAMP |  | 创建时间 |
| `confirmed_at` | DATETIME | 是 | NULL |  | 确认/状态迁移时间 |
| `error_message` | VARCHAR(500) | 是 | NULL |  | 失败摘要 |

状态流：`PENDING → EXECUTING → COMPLETED/FAILED`，或 `PENDING → CANCELLED`。索引 `(session_id, status, created_at DESC)` 支撑查询当前会话待处理动作。状态更新带 `expectedStatus` 条件，实现并发幂等。

## 五、检测与质量域

### 5.1 `detection_task` 检测任务中心表

用途：一张表承载任务创建、OSS 文件、Kafka 调度、模型快照、检测结果、缺陷证据、人工复核、处置、返工及追溯。它是系统最核心的业务聚合表。

#### 基础身份与业务流字段

| 字段名 | 类型 | 可空 | 默认值 | 键/索引 | 含义 |
| --- | --- | --- | --- | --- | --- |
| `id` | BIGINT | 否 | 自增 | PK | 内部主键 |
| `task_id` | VARCHAR(64) | 否 | 无 | UNIQUE | 对外任务编号 |
| `workflow_uuid` | VARCHAR(36) | 是 | NULL | UNIQUE | Agent 可引用工作流 UUID |
| `task_type` | VARCHAR(32) | 否 | `BATCH` |  | `SINGLE`/`BATCH` |
| `batch_no` | VARCHAR(128) | 是 | NULL | INDEX | 批次号 |
| `work_order_no` | VARCHAR(128) | 是 | NULL | INDEX | 工单号 |
| `flow_status` | VARCHAR(32) | 是 | NULL | INDEX | 质量业务流状态 |
| `quality_station` | VARCHAR(64) | 是 | NULL | 复合索引 | 质检站点 |
| `assignee` | VARCHAR(64) | 是 | NULL | 复合索引 | 质检责任人 |
| `assignment_remark` | VARCHAR(500) | 是 | NULL |  | 分派备注 |
| `assigned_at` | DATETIME | 是 | NULL |  | 分派时间 |
| `due_at` | DATETIME | 是 | NULL | INDEX | 截止时间 |

#### 任务调度与模型字段

| 字段名 | 类型 | 可空 | 默认值 | 键/索引 | 含义 |
| --- | --- | --- | --- | --- | --- |
| `status` | VARCHAR(32) | 否 | 无 | INDEX | 总任务状态 |
| `stage` | VARCHAR(32) | 是 | NULL |  | 当前处理阶段 |
| `dispatch_id` | VARCHAR(64) | 是 | NULL |  | 当前 Kafka 派发标识 |
| `last_finished_event_id` | VARCHAR(128) | 是 | NULL |  | 最后完成事件，消费幂等 |
| `model_id` | INT | 是 | NULL | FK、INDEX | 使用模型 |
| `model_version` | VARCHAR(64) | 是 | NULL |  | 模型版本快照 |
| `threshold` | DECIMAL(5,4) | 是 | 0.5000 |  | 检测阈值 |

#### 采集与数量字段

| 字段名 | 类型 | 可空 | 默认值 | 含义 |
| --- | --- | --- | --- | --- |
| `capture_date` | VARCHAR(32) | 是 | NULL | 采集日期文本 |
| `region` | VARCHAR(64) | 是 | NULL | 地区 |
| `collector` | VARCHAR(64) | 是 | NULL | 采集员快照 |
| `device_name` | VARCHAR(128) | 是 | NULL | 设备名称快照 |
| `image_folder_name` | VARCHAR(128) | 是 | NULL | 原始文件夹名 |
| `total_images` | INT | 是 | 0 | 图片总数 |
| `processed_images` | INT | 是 | 0 | 已处理数 |
| `successful_images` | INT | 是 | 0 | 成功数 |
| `failed_images` | INT | 是 | 0 | 失败数 |

#### OSS、结果与缺陷证据字段

| 字段名 | 类型 | 可空 | 默认值 | 键/索引 | 含义 |
| --- | --- | --- | --- | --- | --- |
| `source_oss_prefix` | VARCHAR(255) | 是 | NULL |  | 原图前缀 |
| `result_oss_prefix` | VARCHAR(255) | 是 | NULL |  | 结果前缀 |
| `result_json_oss_key` | VARCHAR(255) | 是 | NULL |  | 结果 JSON Key |
| `original_image_keys_json` | LONGTEXT | 是 | NULL |  | 原图 Key 数组 JSON |
| `preview_image_keys_json` | LONGTEXT | 是 | NULL |  | 标注图 Key 数组 JSON |
| `statistics_json` | LONGTEXT | 是 | NULL |  | 分类统计应用层 JSON |
| `defect_evidence_json` | LONGTEXT | 是 | NULL |  | bbox、置信度、位置等证据 |
| `defect_count` | INT | 否 | 0 |  | 缺陷数 |
| `primary_defect_type` | VARCHAR(64) | 是 | NULL | 复合索引 | 主要缺陷类型 |
| `max_defect_severity` | VARCHAR(32) | 是 | NULL | 复合索引 | `MINOR/MAJOR/CRITICAL` |
| `error_message` | VARCHAR(500) | 是 | NULL |  | 任务错误摘要 |

#### 人工复核与处置字段

| 字段名 | 类型 | 可空 | 默认值 | 含义 |
| --- | --- | --- | --- | --- |
| `review_status` | VARCHAR(32) | 是 | NULL | `PENDING/REVIEWED` |
| `review_conclusion` | VARCHAR(64) | 是 | NULL | 复核结论 |
| `severity_level` | VARCHAR(32) | 是 | NULL | 人工严重等级 |
| `confirmed_defect_count` | INT | 是 | 0 | 确认缺陷数 |
| `false_positive_count` | INT | 是 | 0 | 误报数 |
| `review_remark` | VARCHAR(1000) | 是 | NULL | 复核备注 |
| `reviewer` | VARCHAR(64) | 是 | NULL | 复核人 |
| `reviewed_at` | DATETIME | 是 | NULL | 复核时间 |
| `disposition_status` | VARCHAR(32) | 是 | NULL | `PENDING/DISPOSED` |
| `disposition_action` | VARCHAR(32) | 是 | NULL | `RELEASE/REWORK/RECHECK/HOLD/SCRAP` |
| `disposition_remark` | VARCHAR(1000) | 是 | NULL | 处置备注 |
| `disposition_operator` | VARCHAR(64) | 是 | NULL | 处置人 |
| `disposed_at` | DATETIME | 是 | NULL | 处置时间 |
| `recheck_required` | TINYINT(1) | 否 | 0 | 是否复检 |
| `rework_result` | VARCHAR(64) | 是 | NULL | 返工结果 |
| `rework_operator` | VARCHAR(64) | 是 | NULL | 返工人 |
| `rework_remark` | VARCHAR(1000) | 是 | NULL | 返工备注 |
| `rework_completed_at` | DATETIME | 是 | NULL | 返工完成时间 |

#### 所有者与时间字段

| 字段名 | 类型 | 可空 | 默认值 | 键/属性 | 含义 |
| --- | --- | --- | --- | --- | --- |
| `created_by` | VARCHAR(64) | 是 | NULL | INDEX、逻辑关联 | 创建用户名 |
| `session_id` | VARCHAR(64) | 是 | NULL | FK | 来源 Agent 会话 |
| `created_at` | DATETIME | 是 | CURRENT_TIMESTAMP | INDEX | 创建时间 |
| `started_at` | DATETIME | 是 | NULL |  | 推理开始时间 |
| `finished_at` | DATETIME | 是 | NULL |  | 推理完成时间 |
| `updated_at` | DATETIME | 是 | CURRENT_TIMESTAMP | ON UPDATE | 更新时间 |

真实外键：

- `model_id → model_management.model_id`，删除模型时 `SET NULL`。
- `session_id → chat_session.session_id`，删除会话时 `SET NULL`。

重要复合索引：

- `(status, created_at DESC)`：按状态查看最近任务。
- `(created_by, created_at DESC)`：员工数据隔离和个人任务列表。
- `(assignee, flow_status, due_at)`：责任人质量队列。
- `(quality_station, flow_status, due_at)`：站点质量队列。
- `(device_name, primary_defect_type, created_at DESC)`：设备缺陷追溯。
- `(review_status, reviewed_at DESC)`：复核统计。

## 六、模型治理域

### 6.1 `model_management` 模型管理表

| 字段名 | 类型 | 可空 | 默认值 | 键/索引 | 含义 |
| --- | --- | --- | --- | --- | --- |
| `model_id` | INT | 否 | 无 | PK | 模型主键 |
| `model_name` | VARCHAR(100) | 否 | 无 | 组合唯一 | 模型名称 |
| `version` | VARCHAR(20) | 否 | 无 | 组合唯一 | 版本号 |
| `model_path` | VARCHAR(255) | 否 | 无 |  | ONNX 路径 |
| `upload_time` | DATETIME | 是 | CURRENT_TIMESTAMP | INDEX | 上传时间 |
| `update_description` | VARCHAR(500) | 是 | NULL |  | 更新说明 |
| `status` | VARCHAR(32) | 否 | `READY` | INDEX | `DRAFT/READY/PUBLISHED/DISABLED/ARCHIVED` |
| `is_default` | TINYINT(1) | 否 | 0 | INDEX | 是否默认 |
| `creator` | VARCHAR(64) | 是 | NULL |  | 上传人 |
| `published_at` | DATETIME | 是 | NULL |  | 发布时间 |
| `last_used_at` | DATETIME | 是 | NULL |  | 最近使用 |
| `usage_count` | INT | 否 | 0 |  | 使用次数 |
| `validation_status` | VARCHAR(32) | 否 | `PENDING` | INDEX | `PENDING/PASSED/FAILED` |
| `validation_message` | VARCHAR(255) | 是 | NULL |  | 校验说明 |
| `mlops_status` | VARCHAR(32) | 否 | `UNASSESSED` | INDEX | MLOps 状态 |
| `evaluation_dataset` | VARCHAR(128) | 是 | NULL |  | 评估集 |
| `precision_score` | DECIMAL(8,4) | 是 | NULL |  | 精确率 |
| `recall_score` | DECIMAL(8,4) | 是 | NULL |  | 召回率 |
| `map_score` | DECIMAL(8,4) | 是 | NULL |  | mAP |
| `f1_score` | DECIMAL(8,4) | 是 | NULL |  | F1 |
| `avg_inference_ms` | INT | 是 | NULL |  | 平均推理毫秒 |
| `compatibility_note` | VARCHAR(500) | 是 | NULL |  | 兼容说明 |
| `deployment_strategy` | VARCHAR(32) | 否 | `FULL` | INDEX | `FULL/CANARY/AB_TEST/ROLLBACK` |
| `canary_percent` | INT | 否 | 100 |  | 灰度比例 |
| `ab_group` | VARCHAR(32) | 是 | NULL |  | A/B 分组 |
| `rollback_from_model_id` | INT | 是 | NULL | 逻辑关联 | 回滚来源模型 |

唯一约束 `(model_name, version)` 防止相同模型版本重复上传。`rollback_from_model_id` 当前未建立自引用外键，由应用校验。

### 6.2 `model_operation_log` 模型操作日志

| 字段名 | 类型 | 可空 | 默认值 | 键/索引 | 含义 |
| --- | --- | --- | --- | --- | --- |
| `id` | BIGINT | 否 | 自增 | PK | 日志主键 |
| `model_id` | INT | 否 | 无 | FK、INDEX | 模型 ID |
| `operation_type` | VARCHAR(32) | 否 | 无 |  | `UPLOAD/VALIDATE/PUBLISH/...` |
| `operator` | VARCHAR(64) | 是 | NULL |  | 操作人 |
| `operation_time` | DATETIME | 否 | CURRENT_TIMESTAMP | INDEX | 操作时间 |
| `remark` | VARCHAR(255) | 是 | NULL |  | 备注 |

外键删除策略为 `CASCADE`。索引 `(model_id, operation_time DESC, id DESC)` 支撑模型操作时间线。

## 七、员工与设备域

### 7.1 `employee` 员工表

| 字段名 | 类型 | 可空 | 默认值 | 键/索引 | 含义 |
| --- | --- | --- | --- | --- | --- |
| `id` | BIGINT | 否 | 自增 | PK | 员工主键 |
| `name` | VARCHAR(50) | 否 | 无 |  | 姓名 |
| `employee_number` | VARCHAR(50) | 否 | 无 | UNIQUE | 员工编号 |
| `contact` | VARCHAR(50) | 否 | 无 |  | 联系方式 |
| `department` | VARCHAR(100) | 否 | 无 | INDEX | 部门 |
| `employee_type` | VARCHAR(50) | 否 | 无 | INDEX | `DETECTION/COLLECTION/MAINTENANCE` |
| `gender` | VARCHAR(10) | 否 | 无 |  | 性别 |
| `id_card` | VARCHAR(18) | 是 | NULL | UNIQUE | 身份证号 |
| `hire_date` | DATE | 否 | 无 |  | 入职日期 |
| `status` | VARCHAR(20) | 否 | 无 | INDEX | `ACTIVE/RESIGNED/VACATION` |
| `created_at` | DATETIME | 是 | CURRENT_TIMESTAMP |  | 创建时间 |
| `updated_at` | DATETIME | 是 | CURRENT_TIMESTAMP | ON UPDATE | 更新时间 |

### 7.2 `device_management` 设备表

| 字段名 | 类型 | 可空 | 默认值 | 键/索引 | 含义 |
| --- | --- | --- | --- | --- | --- |
| `id` | BIGINT | 否 | 自增 | PK | 设备主键 |
| `device_code` | VARCHAR(50) | 否 | 无 | UNIQUE | 设备编号 |
| `device_type` | VARCHAR(50) | 否 | 无 | INDEX | `DETECTION/IMAGE_CAPTURE` |
| `model_name` | VARCHAR(100) | 否 | 无 |  | 设备型号 |
| `serial_number` | VARCHAR(100) | 否 | 无 | UNIQUE | 序列号 |
| `status` | VARCHAR(20) | 否 | 无 | INDEX | `IN_USE/MAINTENANCE/IDLE/OFFLINE` |
| `online_status` | VARCHAR(32) | 否 | `OFFLINE` | INDEX | `ONLINE/OFFLINE` |
| `last_heartbeat_at` | DATETIME | 是 | NULL | 复合索引 | 最近心跳 |
| `station_code` | VARCHAR(64) | 是 | NULL | 复合索引 | 工位编号 |
| `edge_node_id` | VARCHAR(64) | 是 | NULL | INDEX | 边缘节点 |
| `plc_status` | VARCHAR(32) | 是 | NULL |  | PLC 状态 |
| `camera_status` | VARCHAR(32) | 是 | NULL |  | 相机状态 |
| `capture_status` | VARCHAR(32) | 是 | NULL |  | 采集状态 |
| `last_image_key` | VARCHAR(255) | 是 | NULL |  | 最近图片 OSS Key |
| `last_capture_at` | DATETIME | 是 | NULL |  | 最近采集时间 |
| `runtime_metadata_json` | LONGTEXT | 是 | NULL |  | 运行态应用层 JSON |
| `last_maintenance_date` | DATETIME | 是 | NULL |  | 最近维护时间 |
| `employee_id` | BIGINT | 是 | NULL | FK、INDEX | 当前使用员工 |
| `created_at` | DATETIME | 是 | CURRENT_TIMESTAMP |  | 创建时间 |
| `updated_at` | DATETIME | 是 | CURRENT_TIMESTAMP | ON UPDATE | 更新时间 |

外键 `employee_id → employee.id ON DELETE SET NULL`。设备删除不会通过该关系删除员工。

### 7.3 `device_capture_alert` 设备告警表

| 字段名 | 类型 | 可空 | 默认值 | 键/索引 | 含义 |
| --- | --- | --- | --- | --- | --- |
| `id` | BIGINT | 否 | 自增 | PK | 主键 |
| `alert_id` | VARCHAR(64) | 否 | 无 | UNIQUE | 告警编号 |
| `device_id` | BIGINT | 是 | NULL | FK | 设备 ID |
| `device_code` | VARCHAR(50) | 否 | 无 | INDEX | 设备编号快照 |
| `device_type` | VARCHAR(50) | 是 | NULL |  | 类型快照 |
| `station_code` | VARCHAR(64) | 是 | NULL | INDEX | 工位 |
| `edge_node_id` | VARCHAR(64) | 是 | NULL |  | 边缘节点 |
| `alert_type` | VARCHAR(64) | 否 | 无 |  | `CAPTURE_EXCEPTION/HEARTBEAT_OFFLINE` |
| `alert_level` | VARCHAR(32) | 否 | `MAJOR` | INDEX | `MINOR/MAJOR/CRITICAL` |
| `alert_message` | VARCHAR(500) | 否 | 无 |  | 告警说明 |
| `runtime_snapshot_json` | LONGTEXT | 是 | NULL |  | 发生时运行快照 |
| `status` | VARCHAR(32) | 否 | `OPEN` | INDEX | `OPEN/ACKNOWLEDGED/RESOLVED` |
| `ack_operator` | VARCHAR(64) | 是 | NULL |  | 确认人 |
| `ack_remark` | VARCHAR(500) | 是 | NULL |  | 确认备注 |
| `acknowledged_at` | DATETIME | 是 | NULL |  | 确认时间 |
| `resolved_operator` | VARCHAR(64) | 是 | NULL |  | 关闭人 |
| `resolved_remark` | VARCHAR(500) | 是 | NULL |  | 关闭备注 |
| `resolved_at` | DATETIME | 是 | NULL |  | 关闭时间 |
| `created_at` | DATETIME | 否 | CURRENT_TIMESTAMP | INDEX | 创建时间 |
| `updated_at` | DATETIME | 否 | CURRENT_TIMESTAMP | ON UPDATE | 更新时间 |

外键 `device_id → device_management.id ON DELETE SET NULL`，同时保留 `device_code` 快照，因此设备删除后告警仍可识别来源。

### 7.4 `device_usage_record` 设备使用记录

| 字段名 | 类型 | 可空 | 默认值 | 键/索引 | 含义 |
| --- | --- | --- | --- | --- | --- |
| `id` | BIGINT | 否 | 自增 | PK | 记录主键 |
| `device_id` | BIGINT | 否 | 无 | FK、INDEX | 设备 ID |
| `device_code` | VARCHAR(50) | 否 | 无 |  | 设备编号快照 |
| `device_type` | VARCHAR(50) | 否 | 无 |  | 类型快照 |
| `model_name` | VARCHAR(100) | 否 | 无 |  | 型号快照 |
| `serial_number` | VARCHAR(100) | 否 | 无 |  | 序列号快照 |
| `employee_id` | BIGINT | 否 | 无 | FK、INDEX | 员工 ID |
| `employee_name` | VARCHAR(50) | 否 | 无 |  | 姓名快照 |
| `employee_number` | VARCHAR(50) | 否 | 无 |  | 员工号快照 |
| `contact` | VARCHAR(50) | 否 | 无 |  | 联系方式快照 |
| `start_time` | DATETIME | 否 | 无 | INDEX | 开始时间 |
| `end_time` | DATETIME | 是 | NULL | INDEX | 结束时间 |
| `status` | VARCHAR(20) | 否 | `IN_USE` | INDEX | `IN_USE/RETURNED` |
| `remarks` | VARCHAR(255) | 是 | NULL |  | 备注 |
| `created_at` | DATETIME | 是 | CURRENT_TIMESTAMP |  | 创建时间 |
| `updated_at` | DATETIME | 是 | CURRENT_TIMESTAMP | ON UPDATE | 更新时间 |

外键对设备和员工均使用 `ON DELETE CASCADE`。表中冗余文本是刻意保存的历史快照，避免人员姓名、设备型号更新后改变历史记录语义。

## 八、典型业务数据流

### 8.1 Agent 创建检测任务

```text
users → chat_session → chat_message
                    → chat_pending_action（写操作确认）
                    → detection_task.session_id
                                      └→ model_management.model_id
```

### 8.2 设备分配与归还

```text
分配：employee + device_management
   → device.employee_id=员工
   → device.status=IN_USE
   → 新增 device_usage_record(status=IN_USE)

归还：usage.end_time=当前时间
   → usage.status=RETURNED
   → device.employee_id=NULL
   → device.status=IDLE
```

### 8.3 检测质量闭环

```text
UPLOADING → UPLOADED → PROCESSING → COMPLETED/PARTIAL_FAILED
→ REVIEWING → CONFIRMED
→ RELEASE / HOLD / REWORK / RECHECK / SCRAP
→ 必要时返工回填并重新进入复核
```

## 九、应用层 JSON 字段

| 表.字段 | 内容 | 说明 |
| --- | --- | --- |
| `chat_session.state_json` | AgentState | Checkpoint 快照 |
| `chat_pending_action.action_payload_json` | 动作参数 | 人工确认后恢复执行 |
| `detection_task.original_image_keys_json` | 字符串数组 | OSS 原图 Key |
| `detection_task.preview_image_keys_json` | 字符串数组 | 标注图 Key |
| `detection_task.statistics_json` | 分类计数和成功率 | Worker 汇总结果 |
| `detection_task.defect_evidence_json` | bbox、置信度、严重度 | 缺陷证据 |
| `device_management.runtime_metadata_json` | PLC/相机等扩展信息 | 运行态扩展 |
| `device_capture_alert.runtime_snapshot_json` | 告警发生时快照 | 排障依据 |

当前使用 `LONGTEXT` 而非 MySQL `JSON`，兼容性和 Java 序列化简单，但数据库无法直接保证 JSON 合法性，也较难建立 JSON 路径索引。

## 十、常用 SQL 与索引对应

```sql
-- 用户最近活跃会话：命中 username/status/updated_at 复合索引
SELECT session_id, title, pinned, updated_at
FROM chat_session
WHERE username = ? AND status = 'ACTIVE'
ORDER BY pinned DESC, updated_at DESC;

-- 责任人待办队列：命中 assignee/flow_status/due_at
SELECT task_id, work_order_no, due_at
FROM detection_task
WHERE assignee = ? AND flow_status = 'REVIEWING'
ORDER BY due_at;

-- 设备缺陷追溯：命中 device_name/primary_defect_type/created_at
SELECT task_id, primary_defect_type, max_defect_severity, created_at
FROM detection_task
WHERE device_name = ? AND primary_defect_type = ?
ORDER BY created_at DESC;

-- 模型操作时间线
SELECT operation_type, operator, operation_time, remark
FROM model_operation_log
WHERE model_id = ?
ORDER BY operation_time DESC, id DESC;
```

## 十一、设计取舍与风险

1. `detection_task` 是宽表，减少质量追溯 JOIN，但字段多、写放大明显；未来数据量很大时可把缺陷明细或质量操作拆表。
2. 状态字段采用 VARCHAR，扩展灵活但数据库未用 CHECK 约束；当前完整性主要由 Service 校验。
3. `capture_date` 使用 VARCHAR，不利于日期范围查询，后续可迁移为 DATE。
4. 多个应用层 JSON 使用 LONGTEXT，未来若需要按 JSON 内字段筛选，可迁移为 JSON 列和生成列索引。
5. `device_usage_record` 对员工和设备使用 CASCADE，可能导致删除主数据时丢失审计历史；生产环境更适合软删除或 RESTRICT。
6. `created_by`、`rollback_from_model_id` 是逻辑关联，数据库不能阻止孤儿值。
7. 索引较多会增加任务写入成本，应根据 `performance_schema` 和慢查询定期审计，不应只增不减。

## 十二、面试问题与答案

### 1. 为什么同时使用自增主键和业务编号？

自增主键适合作为 InnoDB 聚簇索引，写入稳定；`task_id`、`session_id` 等业务编号用于跨系统传递，并通过唯一索引保证幂等。

### 2. `detection_task` 为什么设计成宽表？

检测、质检和追溯页面高频按单个任务读取完整链路，宽表减少多表 JOIN。代价是字段多，因此缺陷明细规模继续增长时应考虑拆分一对多明细表。

### 3. 为什么设备使用记录重复保存姓名和型号？

这些字段是历史快照。员工改名或设备型号修正后，过去的使用记录仍应反映当时信息，这是有目的的反范式设计。

### 4. 复合索引的字段顺序怎么确定？

先放等值过滤字段，再放状态或范围/排序字段。例如 `(assignee, flow_status, due_at)` 对应责任人和状态等值过滤，再按截止时间排序。

### 5. 为什么有些删除使用 SET NULL，有些使用 CASCADE？

检测结果和告警需要尽量保留，因此模型、会话或设备删除时使用 SET NULL；消息依附于会话，模型日志依附于模型，因此使用 CASCADE。设备使用历史当前也使用 CASCADE，但生产审计场景建议改为软删除或 RESTRICT。

### 6. 如何保证 Kafka 完成事件不重复更新任务？

`detection_task` 保存当前 `dispatch_id` 和 `last_finished_event_id`。前者拒绝旧重试批次，后者拒绝同一完成事件重复消费。

### 7. LONGTEXT JSON 与原生 JSON 如何选择？

只由应用整体读写且追求兼容时 LONGTEXT 简单；需要数据库校验、路径查询和生成列索引时应使用原生 JSON。

