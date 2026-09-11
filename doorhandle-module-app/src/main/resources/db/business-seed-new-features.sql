-- Business seed data for newly added industrial inspection features.
-- Safe to re-run: uses deterministic IDs/keys and idempotent updates.

SET NAMES utf8mb4;
SET CHARACTER SET utf8mb4;
SET character_set_connection = utf8mb4;
SET character_set_client = utf8mb4;
SET character_set_results = utf8mb4;

-- ---------------------------------------------------------------------------
-- Model MLOps: evaluation metrics, rollout strategy and operation logs.
-- ---------------------------------------------------------------------------
UPDATE `model_management`
SET `status` = 'PUBLISHED',
    `is_default` = 1,
    `creator` = COALESCE(`creator`, 'system'),
    `published_at` = COALESCE(`published_at`, `upload_time`, NOW()),
    `validation_status` = 'PASSED',
    `validation_message` = 'ONNX 结构、输入输出维度、类别映射校验通过',
    `mlops_status` = 'ROLLOUT',
    `evaluation_dataset` = 'container-door-handle-val-2026Q2',
    `precision_score` = 0.9360,
    `recall_score` = 0.9080,
    `map_score` = 0.9210,
    `f1_score` = 0.9220,
    `avg_inference_ms` = 38,
    `compatibility_note` = 'ONNX Runtime 1.17 / CPU-GPU 混合推理验证通过',
    `deployment_strategy` = 'FULL',
    `canary_percent` = 100,
    `ab_group` = NULL,
    `rollback_from_model_id` = NULL
WHERE `model_id` = 3;

UPDATE `model_management`
SET `status` = 'READY',
    `is_default` = 0,
    `creator` = COALESCE(`creator`, 'mlops-admin'),
    `validation_status` = 'PASSED',
    `validation_message` = '灰度候选模型校验通过',
    `mlops_status` = 'EVALUATED',
    `evaluation_dataset` = 'container-door-handle-hardcase-2026Q2',
    `precision_score` = 0.9480,
    `recall_score` = 0.9010,
    `map_score` = 0.9320,
    `f1_score` = 0.9240,
    `avg_inference_ms` = 46,
    `compatibility_note` = '高精度候选，建议先进行 25% 灰度',
    `deployment_strategy` = 'CANARY',
    `canary_percent` = 25,
    `ab_group` = 'B',
    `rollback_from_model_id` = 3
WHERE `model_id` = 4;

UPDATE `model_management`
SET `status` = 'READY',
    `is_default` = 0,
    `creator` = COALESCE(`creator`, 'mlops-admin'),
    `validation_status` = 'FAILED',
    `validation_message` = '类别顺序与线上配置不一致，暂不允许发布',
    `mlops_status` = 'UNASSESSED',
    `deployment_strategy` = 'FULL',
    `canary_percent` = 0
WHERE `model_id` = 1;

INSERT INTO `model_operation_log` (`model_id`, `operation_type`, `operator`, `operation_time`, `remark`)
SELECT 3, 'EVALUATE', 'mlops-admin', '2026-06-10 09:30:00', '完成 Q2 验证集评估，达到发布阈值'
WHERE EXISTS (SELECT 1 FROM `model_management` WHERE `model_id` = 3)
  AND NOT EXISTS (
      SELECT 1 FROM `model_operation_log`
      WHERE `model_id` = 3 AND `operation_type` = 'EVALUATE' AND `remark` LIKE '完成 Q2%'
  );

INSERT INTO `model_operation_log` (`model_id`, `operation_type`, `operator`, `operation_time`, `remark`)
SELECT 3, 'PUBLISH', 'quality-lead', '2026-06-10 10:00:00', '设为默认生产模型'
WHERE EXISTS (SELECT 1 FROM `model_management` WHERE `model_id` = 3)
  AND NOT EXISTS (
      SELECT 1 FROM `model_operation_log`
      WHERE `model_id` = 3 AND `operation_type` = 'PUBLISH' AND `remark` LIKE '设为默认%'
  );

INSERT INTO `model_operation_log` (`model_id`, `operation_type`, `operator`, `operation_time`, `remark`)
SELECT 4, 'CANARY', 'mlops-admin', '2026-06-12 15:20:00', '候选模型进入 25% 灰度观察'
WHERE EXISTS (SELECT 1 FROM `model_management` WHERE `model_id` = 4)
  AND NOT EXISTS (
      SELECT 1 FROM `model_operation_log`
      WHERE `model_id` = 4 AND `operation_type` = 'CANARY' AND `remark` LIKE '候选模型%'
  );

-- ---------------------------------------------------------------------------
-- Device runtime: station, edge node, heartbeat and capture status.
-- ---------------------------------------------------------------------------
UPDATE `device_management`
SET `online_status` = 'ONLINE',
    `last_heartbeat_at` = '2026-06-15 10:20:00',
    `station_code` = 'LINE-A-ST01',
    `edge_node_id` = 'EDGE-SH-A01',
    `plc_status` = 'OK',
    `camera_status` = 'OK',
    `capture_status` = 'CAPTURING',
    `last_image_key` = 'business/device/DEV-0001/20260615/latest.jpg',
    `last_capture_at` = '2026-06-15 10:19:40',
    `runtime_metadata_json` = '{"line":"A","shift":"day","temperature":36.4,"fps":12,"networkLatencyMs":18}'
WHERE `device_code` = 'DEV-0001';

UPDATE `device_management`
SET `online_status` = 'ONLINE',
    `last_heartbeat_at` = '2026-06-15 10:18:00',
    `station_code` = 'LINE-A-ST02',
    `edge_node_id` = 'EDGE-SH-A02',
    `plc_status` = 'OK',
    `camera_status` = 'WARN',
    `capture_status` = 'LOW_LIGHT',
    `last_image_key` = 'business/device/DEV-0005/20260615/latest.jpg',
    `last_capture_at` = '2026-06-15 10:17:35',
    `runtime_metadata_json` = '{"line":"A","shift":"day","temperature":37.1,"fps":9,"exposure":"auto-high"}'
WHERE `device_code` = 'DEV-0005';

UPDATE `device_management`
SET `online_status` = 'OFFLINE',
    `last_heartbeat_at` = '2026-06-15 09:51:00',
    `station_code` = 'LINE-B-ST03',
    `edge_node_id` = 'EDGE-TJ-B03',
    `plc_status` = 'OK',
    `camera_status` = 'TIMEOUT',
    `capture_status` = 'EXCEPTION',
    `last_image_key` = 'business/device/DEV-0021/20260615/failure.jpg',
    `last_capture_at` = '2026-06-15 09:50:42',
    `runtime_metadata_json` = '{"line":"B","shift":"day","temperature":41.8,"fps":0,"lastError":"camera timeout"}'
WHERE `device_code` = 'DEV-0021';

INSERT INTO `device_capture_alert` (
    `alert_id`, `device_id`, `device_code`, `device_type`, `station_code`, `edge_node_id`,
    `alert_type`, `alert_level`, `alert_message`, `runtime_snapshot_json`, `status`,
    `created_at`, `updated_at`
)
SELECT 'ALERT-BIZ-DEV0021-CAMERA-TIMEOUT', d.`id`, d.`device_code`, d.`device_type`, d.`station_code`, d.`edge_node_id`,
       'CAPTURE_EXCEPTION', 'CRITICAL', '相机连续超时，采集端无新图回传',
       '{"cameraStatus":"TIMEOUT","captureStatus":"EXCEPTION","lastImageKey":"business/device/DEV-0021/20260615/failure.jpg","suggestion":"检查相机供电、网线和边缘节点服务"}',
       'OPEN', '2026-06-15 09:52:00', '2026-06-15 09:52:00'
FROM `device_management` d
WHERE d.`device_code` = 'DEV-0021'
ON DUPLICATE KEY UPDATE
    `device_id` = VALUES(`device_id`),
    `station_code` = VALUES(`station_code`),
    `edge_node_id` = VALUES(`edge_node_id`),
    `alert_level` = VALUES(`alert_level`),
    `alert_message` = VALUES(`alert_message`),
    `runtime_snapshot_json` = VALUES(`runtime_snapshot_json`),
    `status` = VALUES(`status`),
    `updated_at` = VALUES(`updated_at`);

INSERT INTO `device_capture_alert` (
    `alert_id`, `device_id`, `device_code`, `device_type`, `station_code`, `edge_node_id`,
    `alert_type`, `alert_level`, `alert_message`, `runtime_snapshot_json`, `status`,
    `ack_operator`, `ack_remark`, `acknowledged_at`, `created_at`, `updated_at`
)
SELECT 'ALERT-BIZ-DEV0005-LOW-LIGHT', d.`id`, d.`device_code`, d.`device_type`, d.`station_code`, d.`edge_node_id`,
       'CAPTURE_EXCEPTION', 'MAJOR', '工位光照不足，可能影响缺陷框置信度',
       '{"cameraStatus":"WARN","captureStatus":"LOW_LIGHT","fps":9,"suggestion":"补光灯亮度检查"}',
       'ACKNOWLEDGED', 'shift-leader', '已通知现场班组调整补光灯', '2026-06-15 10:05:00',
       '2026-06-15 10:00:00', '2026-06-15 10:05:00'
FROM `device_management` d
WHERE d.`device_code` = 'DEV-0005'
ON DUPLICATE KEY UPDATE
    `device_id` = VALUES(`device_id`),
    `station_code` = VALUES(`station_code`),
    `edge_node_id` = VALUES(`edge_node_id`),
    `alert_level` = VALUES(`alert_level`),
    `alert_message` = VALUES(`alert_message`),
    `runtime_snapshot_json` = VALUES(`runtime_snapshot_json`),
    `status` = VALUES(`status`),
    `ack_operator` = VALUES(`ack_operator`),
    `ack_remark` = VALUES(`ack_remark`),
    `acknowledged_at` = VALUES(`acknowledged_at`),
    `updated_at` = VALUES(`updated_at`);

-- ---------------------------------------------------------------------------
-- Detection closed loop: task assignment, review, disposition and evidence.
-- ---------------------------------------------------------------------------
UPDATE `detection_task`
SET `model_id` = 3,
    `model_version` = 'YOLOv8-m-prod',
    `threshold` = 0.6200,
    `flow_status` = 'PENDING_REVIEW',
    `quality_station` = 'QA-SH-01',
    `assignee` = '李四',
    `assignment_remark` = '严重缺陷优先复核',
    `assigned_at` = '2026-06-15 09:35:00',
    `due_at` = '2026-06-15 12:00:00',
    `defect_evidence_json` = '[{"imageKey":"business/evidence/det_tj_001/original-001.jpg","previewKey":"business/evidence/det_tj_001/annotated-001.jpg","defectType":"RUST","severity":"MAJOR","confidence":0.934,"bbox":{"x":126,"y":88,"w":72,"h":54},"area":3888,"position":"handle-left-hinge"},{"imageKey":"business/evidence/det_tj_001/original-002.jpg","previewKey":"business/evidence/det_tj_001/annotated-002.jpg","defectType":"DEFORMATION","severity":"CRITICAL","confidence":0.912,"bbox":{"x":220,"y":144,"w":96,"h":68},"area":6528,"position":"handle-lock-seat"}]',
    `defect_count` = 2,
    `primary_defect_type` = 'RUST',
    `max_defect_severity` = 'CRITICAL',
    `review_status` = 'PENDING',
    `review_conclusion` = NULL,
    `severity_level` = 'CRITICAL',
    `confirmed_defect_count` = 0,
    `false_positive_count` = 0,
    `review_remark` = NULL,
    `reviewer` = NULL,
    `reviewed_at` = NULL,
    `disposition_status` = NULL,
    `disposition_action` = NULL,
    `disposition_remark` = NULL,
    `disposition_operator` = NULL,
    `disposed_at` = NULL,
    `recheck_required` = 0,
    `rework_result` = NULL,
    `rework_operator` = NULL,
    `rework_remark` = NULL,
    `rework_completed_at` = NULL,
    `statistics_json` = '{"normal":4938,"defect":2,"rust":1,"deformation":1,"critical":1,"major":1}'
WHERE `task_id` = 'det_tj_001';

UPDATE `detection_task`
SET `model_id` = 3,
    `model_version` = 'YOLOv8-m-prod',
    `threshold` = 0.6200,
    `flow_status` = 'CONFIRMED',
    `quality_station` = 'QA-SH-02',
    `assignee` = '王五',
    `assignment_remark` = '已完成复核，等待处置',
    `assigned_at` = '2026-06-15 08:20:00',
    `due_at` = '2026-06-15 11:00:00',
    `defect_evidence_json` = '[{"imageKey":"business/evidence/det_tj_002/original-101.jpg","previewKey":"business/evidence/det_tj_002/annotated-101.jpg","defectType":"MISSING_PART","severity":"CRITICAL","confidence":0.958,"bbox":{"x":172,"y":98,"w":88,"h":80},"area":7040,"position":"handle-pin"}]',
    `defect_count` = 1,
    `primary_defect_type` = 'MISSING_PART',
    `max_defect_severity` = 'CRITICAL',
    `review_status` = 'REVIEWED',
    `review_conclusion` = 'CONFIRMED_DEFECT',
    `severity_level` = 'CRITICAL',
    `confirmed_defect_count` = 1,
    `false_positive_count` = 0,
    `review_remark` = '确认门把手销轴缺失，需隔离并返工',
    `reviewer` = '王五',
    `reviewed_at` = '2026-06-15 09:10:00',
    `disposition_status` = 'PENDING',
    `disposition_action` = NULL,
    `disposition_remark` = NULL,
    `disposition_operator` = NULL,
    `disposed_at` = NULL,
    `recheck_required` = 1,
    `statistics_json` = '{"normal":4559,"defect":1,"missing_part":1,"critical":1}'
WHERE `task_id` = 'det_tj_002';

UPDATE `detection_task`
SET `model_id` = 3,
    `model_version` = 'YOLOv8-m-prod',
    `threshold` = 0.6200,
    `flow_status` = 'REWORK_REQUIRED',
    `quality_station` = 'QA-TJ-01',
    `assignee` = '赵磊',
    `assignment_remark` = '已处置为返工，等待复检',
    `assigned_at` = '2026-06-14 15:30:00',
    `due_at` = '2026-06-15 16:00:00',
    `defect_evidence_json` = '[{"imageKey":"business/evidence/det_tj_003/original-205.jpg","previewKey":"business/evidence/det_tj_003/annotated-205.jpg","defectType":"BEND","severity":"MAJOR","confidence":0.887,"bbox":{"x":208,"y":120,"w":65,"h":90},"area":5850,"position":"handle-grip"}]',
    `defect_count` = 1,
    `primary_defect_type` = 'BEND',
    `max_defect_severity` = 'MAJOR',
    `review_status` = 'REVIEWED',
    `review_conclusion` = 'CONFIRMED_DEFECT',
    `severity_level` = 'MAJOR',
    `confirmed_defect_count` = 1,
    `false_positive_count` = 0,
    `review_remark` = '把手弯曲超出公差',
    `reviewer` = '赵磊',
    `reviewed_at` = '2026-06-14 16:10:00',
    `disposition_status` = 'DISPOSED',
    `disposition_action` = 'REWORK',
    `disposition_remark` = '返工校正后进入复检',
    `disposition_operator` = '质检主管',
    `disposed_at` = '2026-06-14 16:30:00',
    `recheck_required` = 1,
    `rework_result` = 'IN_PROGRESS',
    `rework_operator` = '返工一组',
    `rework_remark` = '正在校正把手弯曲位置',
    `rework_completed_at` = NULL,
    `statistics_json` = '{"normal":5224,"defect":1,"bend":1,"major":1}'
WHERE `task_id` = 'det_tj_003';

UPDATE `detection_task`
SET `model_id` = 3,
    `model_version` = 'YOLOv8-m-prod',
    `threshold` = 0.6200,
    `flow_status` = 'RELEASED',
    `quality_station` = 'QA-TJ-02',
    `assignee` = '张强',
    `assignment_remark` = '误报样本，已放行',
    `assigned_at` = '2026-06-13 14:00:00',
    `due_at` = '2026-06-14 10:00:00',
    `defect_evidence_json` = '[{"imageKey":"business/evidence/det_tj_004/original-302.jpg","previewKey":"business/evidence/det_tj_004/annotated-302.jpg","defectType":"SCRATCH","severity":"MINOR","confidence":0.641,"bbox":{"x":90,"y":72,"w":42,"h":28},"area":1176,"position":"handle-surface"}]',
    `defect_count` = 1,
    `primary_defect_type` = 'SCRATCH',
    `max_defect_severity` = 'MINOR',
    `review_status` = 'REVIEWED',
    `review_conclusion` = 'FALSE_POSITIVE',
    `severity_level` = 'MINOR',
    `confirmed_defect_count` = 0,
    `false_positive_count` = 1,
    `review_remark` = '表面反光导致误检，人工复核为合格',
    `reviewer` = '张强',
    `reviewed_at` = '2026-06-13 15:30:00',
    `disposition_status` = 'DISPOSED',
    `disposition_action` = 'RELEASE',
    `disposition_remark` = '误报确认后放行',
    `disposition_operator` = '质检主管',
    `disposed_at` = '2026-06-13 15:45:00',
    `recheck_required` = 0,
    `rework_result` = NULL,
    `rework_operator` = NULL,
    `rework_remark` = NULL,
    `rework_completed_at` = NULL,
    `statistics_json` = '{"normal":4370,"defect":0,"false_positive":1,"minor":1}'
WHERE `task_id` = 'det_tj_004';

UPDATE `detection_task`
SET `model_id` = 4,
    `model_version` = 'YOLOv8-l-canary',
    `threshold` = 0.7000,
    `flow_status` = 'RECHECK_REQUIRED',
    `quality_station` = 'QA-TJ-03',
    `assignee` = '李静',
    `assignment_remark` = '返工完成，等待复检',
    `assigned_at` = '2026-06-12 11:00:00',
    `due_at` = '2026-06-15 15:30:00',
    `defect_evidence_json` = '[{"imageKey":"business/evidence/det_tj_005/original-410.jpg","previewKey":"business/evidence/det_tj_005/annotated-410.jpg","defectType":"RUST","severity":"MAJOR","confidence":0.902,"bbox":{"x":150,"y":122,"w":74,"h":58},"area":4292,"position":"handle-base"}]',
    `defect_count` = 1,
    `primary_defect_type` = 'RUST',
    `max_defect_severity` = 'MAJOR',
    `review_status` = 'REVIEWED',
    `review_conclusion` = 'CONFIRMED_DEFECT',
    `severity_level` = 'MAJOR',
    `confirmed_defect_count` = 1,
    `false_positive_count` = 0,
    `review_remark` = '锈蚀面积超过阈值',
    `reviewer` = '李静',
    `reviewed_at` = '2026-06-12 11:40:00',
    `disposition_status` = 'DISPOSED',
    `disposition_action` = 'RECHECK',
    `disposition_remark` = '返工除锈后需复检',
    `disposition_operator` = '质检主管',
    `disposed_at` = '2026-06-12 12:00:00',
    `recheck_required` = 1,
    `rework_result` = 'COMPLETED',
    `rework_operator` = '返工二组',
    `rework_remark` = '已完成除锈和补漆',
    `rework_completed_at` = '2026-06-15 09:20:00',
    `statistics_json` = '{"normal":5509,"defect":1,"rust":1,"major":1}'
WHERE `task_id` = 'det_tj_005';
