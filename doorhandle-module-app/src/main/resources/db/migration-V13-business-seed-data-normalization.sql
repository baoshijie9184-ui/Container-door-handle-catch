-- Normalize bundled business seed records so seeded records are treated as ordinary business data.
-- This keeps the one-click trace entries useful while removing demo-only labels from stored fields.

UPDATE `detection_task`
SET `work_order_no` = REPLACE(`work_order_no`, 'WO-DEMO-', 'WO-')
WHERE `work_order_no` LIKE 'WO-DEMO-%';

UPDATE `detection_task`
SET `task_id` = REPLACE(REPLACE(`task_id`, 'demo_task_ext_', 'biz_task_ext_'), 'demo_trace_', 'biz_trace_')
WHERE `task_id` LIKE 'demo_task_ext_%'
   OR `task_id` LIKE 'demo_trace_%';

UPDATE `detection_task`
SET
    `source_oss_prefix` = REPLACE(REPLACE(`source_oss_prefix`, 'demo/tasks/', 'business/tasks/'), 'demo/trace/', 'business/trace/'),
    `result_oss_prefix` = REPLACE(REPLACE(`result_oss_prefix`, 'demo/tasks/', 'business/tasks/'), 'demo/trace/', 'business/trace/'),
    `result_json_oss_key` = REPLACE(REPLACE(`result_json_oss_key`, 'demo/tasks/', 'business/tasks/'), 'demo/trace/', 'business/trace/'),
    `original_image_keys_json` = REPLACE(REPLACE(`original_image_keys_json`, 'demo/tasks/', 'business/tasks/'), 'demo/trace/', 'business/trace/'),
    `preview_image_keys_json` = REPLACE(REPLACE(`preview_image_keys_json`, 'demo/tasks/', 'business/tasks/'), 'demo/trace/', 'business/trace/'),
    `defect_evidence_json` = REPLACE(REPLACE(REPLACE(`defect_evidence_json`, 'demo/evidence/', 'business/evidence/'), 'demo/tasks/', 'business/tasks/'), 'demo/trace/', 'business/trace/')
WHERE `source_oss_prefix` LIKE 'demo/%'
   OR `result_oss_prefix` LIKE 'demo/%'
   OR `result_json_oss_key` LIKE 'demo/%'
   OR `original_image_keys_json` LIKE '%demo/%'
   OR `preview_image_keys_json` LIKE '%demo/%'
   OR `defect_evidence_json` LIKE '%demo/%';

UPDATE `detection_task`
SET
    `assignment_remark` = NULLIF(REPLACE(REPLACE(REPLACE(`assignment_remark`, '演示数据：', ''), '扩展演示：', ''), '追溯演示：', ''), ''),
    `review_remark` = NULLIF(REPLACE(REPLACE(REPLACE(`review_remark`, '演示数据：', ''), '扩展演示：', ''), '追溯演示：', ''), ''),
    `disposition_remark` = NULLIF(REPLACE(REPLACE(REPLACE(`disposition_remark`, '演示数据：', ''), '扩展演示：', ''), '追溯演示：', ''), ''),
    `rework_remark` = NULLIF(REPLACE(REPLACE(REPLACE(`rework_remark`, '演示数据：', ''), '扩展演示：', ''), '追溯演示：', ''), '')
WHERE `assignment_remark` LIKE '演示数据：%'
   OR `assignment_remark` LIKE '扩展演示：%'
   OR `assignment_remark` LIKE '追溯演示：%'
   OR `review_remark` LIKE '演示数据：%'
   OR `review_remark` LIKE '扩展演示：%'
   OR `review_remark` LIKE '追溯演示：%'
   OR `disposition_remark` LIKE '演示数据：%'
   OR `disposition_remark` LIKE '扩展演示：%'
   OR `disposition_remark` LIKE '追溯演示：%'
   OR `rework_remark` LIKE '演示数据：%'
   OR `rework_remark` LIKE '扩展演示：%'
   OR `rework_remark` LIKE '追溯演示：%';

UPDATE `model_management`
SET `validation_message` = NULLIF(REPLACE(REPLACE(`validation_message`, '演示数据：', ''), '扩展演示：', ''), '')
WHERE `validation_message` LIKE '演示数据：%'
   OR `validation_message` LIKE '扩展演示：%';

UPDATE `model_management`
SET `update_description` = NULLIF(REPLACE(REPLACE(`update_description`, '演示数据：', ''), '扩展演示：', ''), '')
WHERE `update_description` LIKE '演示数据：%'
   OR `update_description` LIKE '扩展演示：%';

UPDATE `model_management`
SET `model_path` = REPLACE(`model_path`, '/uploads/models/demo/', '/uploads/models/business/')
WHERE `model_path` LIKE '%/uploads/models/demo/%';

UPDATE `model_operation_log`
SET `remark` = NULLIF(REPLACE(REPLACE(`remark`, '演示数据：', ''), '扩展演示：', ''), '')
WHERE `remark` LIKE '演示数据：%'
   OR `remark` LIKE '扩展演示：%';

UPDATE `device_capture_alert`
SET
    `alert_id` = REPLACE(`alert_id`, 'ALERT-DEMO-', 'ALERT-BIZ-'),
    `alert_message` = NULLIF(REPLACE(REPLACE(`alert_message`, '演示数据：', ''), '扩展演示：', ''), ''),
    `runtime_snapshot_json` = REPLACE(`runtime_snapshot_json`, 'demo/device/', 'business/device/')
WHERE `alert_id` LIKE 'ALERT-DEMO-%'
   OR `alert_message` LIKE '演示数据：%'
   OR `alert_message` LIKE '扩展演示：%'
   OR `runtime_snapshot_json` LIKE '%demo/device/%';

UPDATE `device_management`
SET
    `last_image_key` = REPLACE(`last_image_key`, 'demo/device/', 'business/device/'),
    `runtime_metadata_json` = REPLACE(`runtime_metadata_json`, 'demo/device/', 'business/device/')
WHERE `last_image_key` LIKE 'demo/device/%'
   OR `runtime_metadata_json` LIKE '%demo/device/%';
