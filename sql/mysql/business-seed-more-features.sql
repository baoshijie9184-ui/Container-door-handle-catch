-- More business seed data for the one-stop industrial defect inspection platform.
-- Safe to re-run: deterministic model_id/task_id/alert_id values with upserts.

SET NAMES utf8mb4;
SET CHARACTER SET utf8mb4;
SET character_set_connection = utf8mb4;
SET character_set_client = utf8mb4;
SET character_set_results = utf8mb4;

-- ---------------------------------------------------------------------------
-- Additional model portfolio: production, canary, A/B and rollback examples.
-- ---------------------------------------------------------------------------
INSERT INTO `model_management` (
    `model_id`, `model_name`, `version`, `model_path`, `upload_time`, `update_description`,
    `status`, `is_default`, `creator`, `published_at`, `last_used_at`, `usage_count`,
    `validation_status`, `validation_message`, `mlops_status`, `evaluation_dataset`,
    `precision_score`, `recall_score`, `map_score`, `f1_score`, `avg_inference_ms`,
    `compatibility_note`, `deployment_strategy`, `canary_percent`, `ab_group`, `rollback_from_model_id`
) VALUES
(101, 'DoorHandle-YOLOv8', 'prod-2026.06', '/uploads/models/business/doorhandle-prod-202606.onnx', '2026-06-01 09:00:00', '稳定生产模型',
 'PUBLISHED', 0, 'mlops-admin', '2026-06-01 10:00:00', '2026-06-15 10:30:00', 286,
 'PASSED', '线上验证通过', 'ROLLOUT', 'doorhandle-prod-val-202606',
 0.9410, 0.9160, 0.9270, 0.9280, 36, 'CPU/GPU 双环境通过，适合主线批量检测', 'FULL', 100, NULL, NULL),
(102, 'DoorHandle-YOLOv8', 'canary-2026.06-a', '/uploads/models/business/doorhandle-canary-a-202606.onnx', '2026-06-08 14:00:00', '灰度候选 A',
 'READY', 0, 'mlops-admin', NULL, '2026-06-15 09:10:00', 48,
 'PASSED', '困难样本召回提升', 'ROLLOUT', 'doorhandle-hardcase-val-202606',
 0.9320, 0.9410, 0.9360, 0.9360, 44, '召回更高，已进入 30% 灰度', 'CANARY', 30, 'A', 101),
(103, 'DoorHandle-YOLOv8', 'ab-2026.06-b', '/uploads/models/business/doorhandle-ab-b-202606.onnx', '2026-06-09 11:20:00', 'A/B 分组 B',
 'READY', 0, 'mlops-admin', NULL, '2026-06-15 08:50:00', 35,
 'PASSED', '低光照样本表现更稳', 'ROLLOUT', 'doorhandle-lowlight-val-202606',
 0.9250, 0.9340, 0.9290, 0.9290, 42, '低光照工位推荐进入 B 组', 'AB_TEST', 50, 'B', 101),
(104, 'DoorHandle-YOLOv8', 'rb-safe-2026.05', '/uploads/models/business/doorhandle-rollback-safe-202605.onnx', '2026-05-18 17:30:00', '安全回滚版本',
 'PUBLISHED', 0, 'quality-lead', '2026-05-18 18:00:00', '2026-06-12 17:00:00', 612,
 'PASSED', '长期稳定版本', 'ROLLED_BACK', 'doorhandle-baseline-202605',
 0.9180, 0.8970, 0.9050, 0.9070, 31, '可作为异常时的安全回滚目标', 'ROLLBACK', 0, NULL, 101)
ON DUPLICATE KEY UPDATE
    `model_name` = VALUES(`model_name`),
    `version` = VALUES(`version`),
    `model_path` = VALUES(`model_path`),
    `update_description` = VALUES(`update_description`),
    `status` = VALUES(`status`),
    `is_default` = VALUES(`is_default`),
    `creator` = VALUES(`creator`),
    `published_at` = VALUES(`published_at`),
    `last_used_at` = VALUES(`last_used_at`),
    `usage_count` = VALUES(`usage_count`),
    `validation_status` = VALUES(`validation_status`),
    `validation_message` = VALUES(`validation_message`),
    `mlops_status` = VALUES(`mlops_status`),
    `evaluation_dataset` = VALUES(`evaluation_dataset`),
    `precision_score` = VALUES(`precision_score`),
    `recall_score` = VALUES(`recall_score`),
    `map_score` = VALUES(`map_score`),
    `f1_score` = VALUES(`f1_score`),
    `avg_inference_ms` = VALUES(`avg_inference_ms`),
    `compatibility_note` = VALUES(`compatibility_note`),
    `deployment_strategy` = VALUES(`deployment_strategy`),
    `canary_percent` = VALUES(`canary_percent`),
    `ab_group` = VALUES(`ab_group`),
    `rollback_from_model_id` = VALUES(`rollback_from_model_id`);

INSERT INTO `model_operation_log` (`model_id`, `operation_type`, `operator`, `operation_time`, `remark`)
SELECT x.`model_id`, x.`operation_type`, x.`operator`, x.`operation_time`, x.`remark`
FROM (
    SELECT 101 AS model_id, 'PUBLISH' AS operation_type, 'quality-lead' AS operator, '2026-06-01 10:00:00' AS operation_time, '生产模型发布' AS remark
    UNION ALL SELECT 102, 'CANARY', 'mlops-admin', '2026-06-10 09:00:00', '30% 灰度观察'
    UNION ALL SELECT 103, 'AB_TEST', 'mlops-admin', '2026-06-10 10:30:00', '低光照工位进入 B 组'
    UNION ALL SELECT 104, 'ROLLBACK', 'quality-lead', '2026-06-12 17:00:00', '保留安全回滚版本'
) x
WHERE NOT EXISTS (
    SELECT 1 FROM `model_operation_log` l
    WHERE l.`model_id` = x.`model_id`
      AND l.`operation_type` = x.`operation_type`
      AND l.`remark` = x.`remark`
);

-- ---------------------------------------------------------------------------
-- More device runtime snapshots.
-- ---------------------------------------------------------------------------
UPDATE `device_management` SET `online_status`='ONLINE', `last_heartbeat_at`='2026-06-15 10:31:00', `station_code`='LINE-A-ST03', `edge_node_id`='EDGE-SH-A03', `plc_status`='OK', `camera_status`='OK', `capture_status`='CAPTURING', `last_image_key`='business/device/DEV-0006/20260615/latest.jpg', `last_capture_at`='2026-06-15 10:30:48', `runtime_metadata_json`='{"line":"A","station":"ST03","shift":"day","fps":11,"temperature":35.8}' WHERE `device_code`='DEV-0006';
UPDATE `device_management` SET `online_status`='ONLINE', `last_heartbeat_at`='2026-06-15 10:30:30', `station_code`='LINE-A-ST04', `edge_node_id`='EDGE-SH-A04', `plc_status`='OK', `camera_status`='OK', `capture_status`='IDLE', `last_image_key`='business/device/DEV-0008/20260615/latest.jpg', `last_capture_at`='2026-06-15 10:29:55', `runtime_metadata_json`='{"line":"A","station":"ST04","shift":"day","fps":10,"temperature":36.1}' WHERE `device_code`='DEV-0008';
UPDATE `device_management` SET `online_status`='ONLINE', `last_heartbeat_at`='2026-06-15 10:28:45', `station_code`='LINE-B-ST01', `edge_node_id`='EDGE-TJ-B01', `plc_status`='OK', `camera_status`='WARN', `capture_status`='LOW_LIGHT', `last_image_key`='business/device/DEV-0010/20260615/latest.jpg', `last_capture_at`='2026-06-15 10:28:10', `runtime_metadata_json`='{"line":"B","station":"ST01","shift":"day","fps":8,"lux":62}' WHERE `device_code`='DEV-0010';
UPDATE `device_management` SET `online_status`='OFFLINE', `last_heartbeat_at`='2026-06-15 09:45:20', `station_code`='LINE-B-ST02', `edge_node_id`='EDGE-TJ-B02', `plc_status`='OK', `camera_status`='DISCONNECTED', `capture_status`='EXCEPTION', `last_image_key`='business/device/DEV-0011/20260615/failure.jpg', `last_capture_at`='2026-06-15 09:44:56', `runtime_metadata_json`='{"line":"B","station":"ST02","shift":"day","fps":0,"lastError":"camera disconnected"}' WHERE `device_code`='DEV-0011';
UPDATE `device_management` SET `online_status`='ONLINE', `last_heartbeat_at`='2026-06-15 10:29:50', `station_code`='LINE-C-ST01', `edge_node_id`='EDGE-NJ-C01', `plc_status`='WARN', `camera_status`='OK', `capture_status`='CAPTURING', `last_image_key`='business/device/DEV-0015/20260615/latest.jpg', `last_capture_at`='2026-06-15 10:29:20', `runtime_metadata_json`='{"line":"C","station":"ST01","shift":"day","fps":12,"plcCycleMs":180}' WHERE `device_code`='DEV-0015';
UPDATE `device_management` SET `online_status`='ONLINE', `last_heartbeat_at`='2026-06-15 10:27:05', `station_code`='LINE-C-ST02', `edge_node_id`='EDGE-NJ-C02', `plc_status`='OK', `camera_status`='OK', `capture_status`='CAPTURING', `last_image_key`='business/device/DEV-0016/20260615/latest.jpg', `last_capture_at`='2026-06-15 10:26:40', `runtime_metadata_json`='{"line":"C","station":"ST02","shift":"day","fps":13,"temperature":34.9}' WHERE `device_code`='DEV-0016';
UPDATE `device_management` SET `online_status`='OFFLINE', `last_heartbeat_at`='2026-06-15 09:38:00', `station_code`='LINE-C-ST03', `edge_node_id`='EDGE-NJ-C03', `plc_status`='TIMEOUT', `camera_status`='OK', `capture_status`='EXCEPTION', `last_image_key`='business/device/DEV-0018/20260615/failure.jpg', `last_capture_at`='2026-06-15 09:37:30', `runtime_metadata_json`='{"line":"C","station":"ST03","shift":"day","fps":0,"lastError":"plc timeout"}' WHERE `device_code`='DEV-0018';
UPDATE `device_management` SET `online_status`='ONLINE', `last_heartbeat_at`='2026-06-15 10:26:20', `station_code`='LINE-D-ST01', `edge_node_id`='EDGE-GZ-D01', `plc_status`='OK', `camera_status`='OK', `capture_status`='CAPTURING', `last_image_key`='business/device/DEV-0020/20260615/latest.jpg', `last_capture_at`='2026-06-15 10:25:58', `runtime_metadata_json`='{"line":"D","station":"ST01","shift":"day","fps":12,"networkLatencyMs":21}' WHERE `device_code`='DEV-0020';
UPDATE `device_management` SET `online_status`='ONLINE', `last_heartbeat_at`='2026-06-15 10:25:40', `station_code`='LINE-D-ST02', `edge_node_id`='EDGE-GZ-D02', `plc_status`='OK', `camera_status`='DIRTY_LENS', `capture_status`='BLUR', `last_image_key`='business/device/DEV-0023/20260615/latest.jpg', `last_capture_at`='2026-06-15 10:25:10', `runtime_metadata_json`='{"line":"D","station":"ST02","shift":"day","fps":7,"blurScore":0.74}' WHERE `device_code`='DEV-0023';
UPDATE `device_management` SET `online_status`='ONLINE', `last_heartbeat_at`='2026-06-15 10:24:55', `station_code`='LINE-D-ST03', `edge_node_id`='EDGE-GZ-D03', `plc_status`='OK', `camera_status`='OK', `capture_status`='CAPTURING', `last_image_key`='business/device/DEV-0025/20260615/latest.jpg', `last_capture_at`='2026-06-15 10:24:33', `runtime_metadata_json`='{"line":"D","station":"ST03","shift":"day","fps":12,"temperature":35.2}' WHERE `device_code`='DEV-0025';
UPDATE `device_management` SET `online_status`='OFFLINE', `last_heartbeat_at`='2026-06-15 08:55:00', `station_code`='LINE-E-ST01', `edge_node_id`='EDGE-CD-E01', `plc_status`='POWER_LOSS', `camera_status`='OFFLINE', `capture_status`='EXCEPTION', `last_image_key`='business/device/DEV-0028/20260615/failure.jpg', `last_capture_at`='2026-06-15 08:54:30', `runtime_metadata_json`='{"line":"E","station":"ST01","shift":"day","fps":0,"lastError":"power loss"}' WHERE `device_code`='DEV-0028';
UPDATE `device_management` SET `online_status`='ONLINE', `last_heartbeat_at`='2026-06-15 10:23:30', `station_code`='LINE-E-ST02', `edge_node_id`='EDGE-CD-E02', `plc_status`='OK', `camera_status`='OK', `capture_status`='CAPTURING', `last_image_key`='business/device/DEV-0030/20260615/latest.jpg', `last_capture_at`='2026-06-15 10:23:00', `runtime_metadata_json`='{"line":"E","station":"ST02","shift":"day","fps":11,"networkLatencyMs":19}' WHERE `device_code`='DEV-0030';

-- ---------------------------------------------------------------------------
-- More capture alerts.
-- ---------------------------------------------------------------------------
INSERT INTO `device_capture_alert` (
    `alert_id`, `device_id`, `device_code`, `device_type`, `station_code`, `edge_node_id`,
    `alert_type`, `alert_level`, `alert_message`, `runtime_snapshot_json`, `status`,
    `ack_operator`, `ack_remark`, `acknowledged_at`, `resolved_operator`, `resolved_remark`, `resolved_at`,
    `created_at`, `updated_at`
)
SELECT x.`alert_id`, d.`id`, d.`device_code`, d.`device_type`, d.`station_code`, d.`edge_node_id`,
       x.`alert_type`, x.`alert_level`, x.`alert_message`, x.`runtime_snapshot_json`, x.`status`,
       x.`ack_operator`, x.`ack_remark`, x.`acknowledged_at`, x.`resolved_operator`, x.`resolved_remark`, x.`resolved_at`,
       x.`created_at`, x.`updated_at`
FROM (
    SELECT 'ALERT-BIZ-DEV0010-LOW-LIGHT' AS alert_id, 'DEV-0010' AS device_code, 'CAPTURE_EXCEPTION' AS alert_type, 'MAJOR' AS alert_level, '低光照导致置信度下降' AS alert_message, '{"cameraStatus":"WARN","captureStatus":"LOW_LIGHT","lux":62}' AS runtime_snapshot_json, 'OPEN' AS status, NULL AS ack_operator, NULL AS ack_remark, NULL AS acknowledged_at, NULL AS resolved_operator, NULL AS resolved_remark, NULL AS resolved_at, '2026-06-15 10:28:50' AS created_at, '2026-06-15 10:28:50' AS updated_at
    UNION ALL SELECT 'ALERT-BIZ-DEV0011-CAMERA-DISCONNECTED','DEV-0011','CAPTURE_EXCEPTION','CRITICAL','相机断开连接','{"cameraStatus":"DISCONNECTED","captureStatus":"EXCEPTION"}','OPEN',NULL,NULL,NULL,NULL,NULL,NULL,'2026-06-15 09:46:00','2026-06-15 09:46:00'
    UNION ALL SELECT 'ALERT-BIZ-DEV0015-PLC-WARN','DEV-0015','CAPTURE_EXCEPTION','MINOR','PLC 周期抖动偏高','{"plcStatus":"WARN","plcCycleMs":180}','ACKNOWLEDGED','shift-leader','已安排自动化工程师观察', '2026-06-15 10:05:00',NULL,NULL,NULL,'2026-06-15 09:58:00','2026-06-15 10:05:00'
    UNION ALL SELECT 'ALERT-BIZ-DEV0018-PLC-TIMEOUT','DEV-0018','CAPTURE_EXCEPTION','CRITICAL','PLC 心跳超时','{"plcStatus":"TIMEOUT","captureStatus":"EXCEPTION"}','OPEN',NULL,NULL,NULL,NULL,NULL,NULL,'2026-06-15 09:39:00','2026-06-15 09:39:00'
    UNION ALL SELECT 'ALERT-BIZ-DEV0023-DIRTY-LENS','DEV-0023','CAPTURE_EXCEPTION','MAJOR','镜头污染导致图像模糊','{"cameraStatus":"DIRTY_LENS","captureStatus":"BLUR","blurScore":0.74}','ACKNOWLEDGED','quality-lead','已通知现场擦拭镜头','2026-06-15 10:26:00',NULL,NULL,NULL,'2026-06-15 10:25:40','2026-06-15 10:26:00'
    UNION ALL SELECT 'ALERT-BIZ-DEV0028-POWER-LOSS','DEV-0028','CAPTURE_EXCEPTION','CRITICAL','工位电源异常','{"plcStatus":"POWER_LOSS","cameraStatus":"OFFLINE"}','RESOLVED','maintenance','已切换备用电源','2026-06-15 09:05:00','maintenance','电源恢复，设备待复位','2026-06-15 09:30:00','2026-06-15 08:56:00','2026-06-15 09:30:00'
    UNION ALL SELECT 'ALERT-BIZ-DEV0021-CAMERA-RECOVERING','DEV-0021','CAPTURE_EXCEPTION','MAJOR','相机重连后图像帧率偏低','{"cameraStatus":"RECOVERING","fps":5}','ACKNOWLEDGED','shift-leader','重连恢复中，持续观察','2026-06-15 10:12:00',NULL,NULL,NULL,'2026-06-15 10:10:00','2026-06-15 10:12:00'
    UNION ALL SELECT 'ALERT-BIZ-DEV0006-NETWORK-JITTER','DEV-0006','CAPTURE_EXCEPTION','MINOR','边缘节点网络抖动','{"networkLatencyMs":96,"packetLoss":0.02}','RESOLVED','it-ops','已切换交换机端口','2026-06-15 10:02:00','it-ops','网络恢复稳定','2026-06-15 10:18:00','2026-06-15 09:59:00','2026-06-15 10:18:00'
) x
JOIN `device_management` d ON d.`device_code` = x.`device_code`
ON DUPLICATE KEY UPDATE
    `device_id` = VALUES(`device_id`),
    `device_type` = VALUES(`device_type`),
    `station_code` = VALUES(`station_code`),
    `edge_node_id` = VALUES(`edge_node_id`),
    `alert_type` = VALUES(`alert_type`),
    `alert_level` = VALUES(`alert_level`),
    `alert_message` = VALUES(`alert_message`),
    `runtime_snapshot_json` = VALUES(`runtime_snapshot_json`),
    `status` = VALUES(`status`),
    `ack_operator` = VALUES(`ack_operator`),
    `ack_remark` = VALUES(`ack_remark`),
    `acknowledged_at` = VALUES(`acknowledged_at`),
    `resolved_operator` = VALUES(`resolved_operator`),
    `resolved_remark` = VALUES(`resolved_remark`),
    `resolved_at` = VALUES(`resolved_at`),
    `updated_at` = VALUES(`updated_at`);

-- ---------------------------------------------------------------------------
-- Additional end-to-end detection tasks across review/disposition queues.
-- ---------------------------------------------------------------------------
INSERT INTO `detection_task` (
    `task_id`, `workflow_uuid`, `task_type`, `batch_no`, `work_order_no`, `flow_status`,
    `quality_station`, `assignee`, `assignment_remark`, `assigned_at`, `due_at`,
    `status`, `stage`, `model_id`, `model_version`, `threshold`, `capture_date`, `region`,
    `collector`, `device_name`, `image_folder_name`, `total_images`, `processed_images`,
    `successful_images`, `failed_images`, `source_oss_prefix`, `result_oss_prefix`, `result_json_oss_key`,
    `original_image_keys_json`, `preview_image_keys_json`, `statistics_json`, `defect_evidence_json`,
    `defect_count`, `primary_defect_type`, `max_defect_severity`, `error_message`, `review_status`,
    `review_conclusion`, `severity_level`, `confirmed_defect_count`, `false_positive_count`,
    `review_remark`, `reviewer`, `reviewed_at`, `disposition_status`, `disposition_action`,
    `disposition_remark`, `disposition_operator`, `disposed_at`, `recheck_required`,
    `rework_result`, `rework_operator`, `rework_remark`, `rework_completed_at`, `created_by`,
    `created_at`, `started_at`, `finished_at`, `updated_at`
) VALUES
('biz_task_ext_001','90000000-0000-4000-8000-000000000001','BATCH','BATCH-SH-A-20260615-001','WO-SH-A-001','PENDING_REVIEW','QA-SH-01','李四','新批次严重缺陷优先复核','2026-06-15 10:05:00','2026-06-15 13:00:00','COMPLETED','COMPLETED',101,'prod-2026.06',0.6200,'2026-06-15','上海','张三','DEV-0001','A-001',2400,2400,2396,4,'business/tasks/ext001/original/','business/tasks/ext001/result/','business/tasks/ext001/result/result.json','["business/tasks/ext001/original/001.jpg"]','["business/tasks/ext001/result/001.jpg"]','{"normal":2396,"defect":4,"rust":2,"bend":1,"missing_part":1}','[{"imageKey":"business/tasks/ext001/original/001.jpg","previewKey":"business/tasks/ext001/result/001.jpg","defectType":"RUST","severity":"MAJOR","confidence":0.927,"bbox":{"x":140,"y":80,"w":66,"h":48},"area":3168,"position":"handle-base"},{"imageKey":"business/tasks/ext001/original/002.jpg","previewKey":"business/tasks/ext001/result/002.jpg","defectType":"MISSING_PART","severity":"CRITICAL","confidence":0.951,"bbox":{"x":210,"y":122,"w":84,"h":76},"area":6384,"position":"pin-hole"}]',4,'RUST','CRITICAL',NULL,'PENDING',NULL,'CRITICAL',0,0,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,0,NULL,NULL,NULL,NULL,'admin','2026-06-15 09:58:00','2026-06-15 09:59:00','2026-06-15 10:04:00','2026-06-15 10:05:00'),
('biz_task_ext_002','90000000-0000-4000-8000-000000000002','BATCH','BATCH-SH-A-20260615-002','WO-SH-A-002','CONFIRMED','QA-SH-02','王五','已确认缺陷，待处置','2026-06-15 09:30:00','2026-06-15 12:30:00','COMPLETED','COMPLETED',102,'canary-2026.06-a',0.6500,'2026-06-15','上海','李四','DEV-0005','A-002',1800,1800,1798,2,'business/tasks/ext002/original/','business/tasks/ext002/result/','business/tasks/ext002/result/result.json','["business/tasks/ext002/original/001.jpg"]','["business/tasks/ext002/result/001.jpg"]','{"normal":1798,"defect":2,"deformation":2}','[{"imageKey":"business/tasks/ext002/original/001.jpg","previewKey":"business/tasks/ext002/result/001.jpg","defectType":"DEFORMATION","severity":"MAJOR","confidence":0.889,"bbox":{"x":166,"y":104,"w":72,"h":63},"area":4536,"position":"handle-seat"}]',2,'DEFORMATION','MAJOR',NULL,'REVIEWED','CONFIRMED_DEFECT','MAJOR',2,0,'确认把手座变形','王五','2026-06-15 10:12:00','PENDING',NULL,NULL,NULL,NULL,1,NULL,NULL,NULL,NULL,'admin','2026-06-15 09:20:00','2026-06-15 09:21:00','2026-06-15 09:28:00','2026-06-15 10:12:00'),
('biz_task_ext_003','90000000-0000-4000-8000-000000000003','BATCH','BATCH-TJ-B-20260615-001','WO-TJ-B-001','REWORK_REQUIRED','QA-TJ-01','赵磊','返工中','2026-06-15 08:30:00','2026-06-15 17:00:00','COMPLETED','COMPLETED',101,'prod-2026.06',0.6200,'2026-06-15','天津','王芳','DEV-0010','B-001',3200,3200,3199,1,'business/tasks/ext003/original/','business/tasks/ext003/result/','business/tasks/ext003/result/result.json','["business/tasks/ext003/original/001.jpg"]','["business/tasks/ext003/result/001.jpg"]','{"normal":3199,"defect":1,"bend":1}','[{"imageKey":"business/tasks/ext003/original/001.jpg","previewKey":"business/tasks/ext003/result/001.jpg","defectType":"BEND","severity":"MAJOR","confidence":0.902,"bbox":{"x":118,"y":130,"w":80,"h":60},"area":4800,"position":"handle-grip"}]',1,'BEND','MAJOR',NULL,'REVIEWED','CONFIRMED_DEFECT','MAJOR',1,0,'弯曲超差','赵磊','2026-06-15 09:00:00','DISPOSED','REWORK','安排返工校正','质检主管','2026-06-15 09:10:00',1,'IN_PROGRESS','返工一组','夹具校正中',NULL,'admin','2026-06-15 08:20:00','2026-06-15 08:21:00','2026-06-15 08:28:00','2026-06-15 09:10:00'),
('biz_task_ext_004','90000000-0000-4000-8000-000000000004','BATCH','BATCH-NJ-C-20260615-001','WO-NJ-C-001','RECHECK_REQUIRED','QA-NJ-01','李静','返工完成待复检','2026-06-15 07:50:00','2026-06-15 15:00:00','COMPLETED','COMPLETED',103,'ab-2026.06-b',0.6800,'2026-06-15','南京','刘伟','DEV-0015','C-001',2600,2600,2598,2,'business/tasks/ext004/original/','business/tasks/ext004/result/','business/tasks/ext004/result/result.json','["business/tasks/ext004/original/001.jpg"]','["business/tasks/ext004/result/001.jpg"]','{"normal":2598,"defect":2,"rust":2}','[{"imageKey":"business/tasks/ext004/original/001.jpg","previewKey":"business/tasks/ext004/result/001.jpg","defectType":"RUST","severity":"MAJOR","confidence":0.918,"bbox":{"x":188,"y":96,"w":70,"h":58},"area":4060,"position":"handle-base"}]',2,'RUST','MAJOR',NULL,'REVIEWED','CONFIRMED_DEFECT','MAJOR',2,0,'锈蚀已确认','李静','2026-06-15 08:20:00','DISPOSED','RECHECK','返工除锈后复检','质检主管','2026-06-15 08:30:00',1,'COMPLETED','返工二组','已除锈补漆','2026-06-15 10:20:00','admin','2026-06-15 07:40:00','2026-06-15 07:41:00','2026-06-15 07:48:00','2026-06-15 10:20:00'),
('biz_task_ext_005','90000000-0000-4000-8000-000000000005','BATCH','BATCH-GZ-D-20260615-001','WO-GZ-D-001','RELEASED','QA-GZ-01','张强','误报放行','2026-06-14 14:00:00','2026-06-15 10:00:00','COMPLETED','COMPLETED',101,'prod-2026.06',0.6200,'2026-06-14','广州','张强','DEV-0020','D-001',2100,2100,2100,0,'business/tasks/ext005/original/','business/tasks/ext005/result/','business/tasks/ext005/result/result.json','["business/tasks/ext005/original/001.jpg"]','["business/tasks/ext005/result/001.jpg"]','{"normal":2100,"defect":0,"false_positive":1}','[{"imageKey":"business/tasks/ext005/original/001.jpg","previewKey":"business/tasks/ext005/result/001.jpg","defectType":"SCRATCH","severity":"MINOR","confidence":0.604,"bbox":{"x":96,"y":88,"w":40,"h":26},"area":1040,"position":"reflection-zone"}]',1,'SCRATCH','MINOR',NULL,'REVIEWED','FALSE_POSITIVE','MINOR',0,1,'反光误报','张强','2026-06-14 15:00:00','DISPOSED','RELEASE','复核合格放行','质检主管','2026-06-14 15:05:00',0,NULL,NULL,NULL,NULL,'admin','2026-06-14 13:50:00','2026-06-14 13:51:00','2026-06-14 13:58:00','2026-06-14 15:05:00'),
('biz_task_ext_006','90000000-0000-4000-8000-000000000006','BATCH','BATCH-CD-E-20260615-001','WO-CD-E-001','HOLD','QA-CD-01','王五','隔离待工程判定','2026-06-15 09:00:00','2026-06-15 18:00:00','COMPLETED','COMPLETED',104,'rb-safe-2026.05',0.6000,'2026-06-15','成都','陈二','DEV-0028','E-001',1600,1600,1597,3,'business/tasks/ext006/original/','business/tasks/ext006/result/','business/tasks/ext006/result/result.json','["business/tasks/ext006/original/001.jpg"]','["business/tasks/ext006/result/001.jpg"]','{"normal":1597,"defect":3,"missing_part":1,"deformation":2}','[{"imageKey":"business/tasks/ext006/original/001.jpg","previewKey":"business/tasks/ext006/result/001.jpg","defectType":"MISSING_PART","severity":"CRITICAL","confidence":0.963,"bbox":{"x":230,"y":110,"w":90,"h":84},"area":7560,"position":"locking-pin"}]',3,'MISSING_PART','CRITICAL',NULL,'REVIEWED','CONFIRMED_DEFECT','CRITICAL',3,0,'关键件缺失，隔离等待工程处理','王五','2026-06-15 09:35:00','DISPOSED','HOLD','整批隔离','质检主管','2026-06-15 09:45:00',1,NULL,NULL,NULL,NULL,'admin','2026-06-15 08:50:00','2026-06-15 08:51:00','2026-06-15 08:58:00','2026-06-15 09:45:00'),
('biz_task_ext_007','90000000-0000-4000-8000-000000000007','BATCH','BATCH-SH-A-20260615-003','WO-SH-A-003','PENDING_DETECTION','QA-SH-03',NULL,'上传完成等待检测',NULL,NULL,'UPLOADED','PENDING_DETECTION',102,'canary-2026.06-a',0.6500,'2026-06-15','上海','刘一','DEV-0006','A-003',1200,0,0,0,'business/tasks/ext007/original/',NULL,NULL,'["business/tasks/ext007/original/001.jpg"]',NULL,'{"normal":0,"defect":0}',NULL,0,NULL,NULL,NULL,NULL,NULL,NULL,0,0,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,0,NULL,NULL,NULL,NULL,'admin','2026-06-15 10:18:00',NULL,NULL,'2026-06-15 10:18:00'),
('biz_task_ext_008','90000000-0000-4000-8000-000000000008','BATCH','BATCH-NJ-C-20260615-002','WO-NJ-C-002','DETECTING','QA-NJ-02',NULL,'检测中',NULL,NULL,'DETECTING','DETECTING',103,'ab-2026.06-b',0.6800,'2026-06-15','南京','李静','DEV-0016','C-002',3000,1880,1878,2,'business/tasks/ext008/original/','business/tasks/ext008/result/',NULL,'["business/tasks/ext008/original/001.jpg"]','["business/tasks/ext008/result/001.jpg"]','{"normal":1878,"defect":2}',NULL,0,NULL,NULL,NULL,NULL,NULL,NULL,0,0,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,0,NULL,NULL,NULL,NULL,'admin','2026-06-15 10:00:00','2026-06-15 10:01:00',NULL,'2026-06-15 10:22:00'),
('biz_task_ext_009','90000000-0000-4000-8000-000000000009','BATCH','BATCH-GZ-D-20260615-002','WO-GZ-D-002','FAILED','QA-GZ-02',NULL,'采集图像缺失导致失败',NULL,NULL,'FAILED','FAILED',101,'prod-2026.06',0.6200,'2026-06-15','广州','赵磊','DEV-0023','D-002',900,0,0,900,'business/tasks/ext009/original/',NULL,NULL,NULL,NULL,'{"normal":0,"defect":0}','[]',0,NULL,NULL,'OSS 前缀下未找到有效图片','PENDING',NULL,NULL,0,0,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,0,NULL,NULL,NULL,NULL,'admin','2026-06-15 09:35:00','2026-06-15 09:36:00','2026-06-15 09:37:00','2026-06-15 09:37:00'),
('biz_task_ext_010','90000000-0000-4000-8000-000000000010','BATCH','BATCH-SH-A-20260615-004','WO-SH-A-004','SCRAPPED','QA-SH-04','李四','严重损伤报废','2026-06-13 09:00:00','2026-06-13 16:00:00','COMPLETED','COMPLETED',101,'prod-2026.06',0.6200,'2026-06-13','上海','张三','DEV-0008','A-004',1400,1400,1398,2,'business/tasks/ext010/original/','business/tasks/ext010/result/','business/tasks/ext010/result/result.json','["business/tasks/ext010/original/001.jpg"]','["business/tasks/ext010/result/001.jpg"]','{"normal":1398,"defect":2,"crack":2}','[{"imageKey":"business/tasks/ext010/original/001.jpg","previewKey":"business/tasks/ext010/result/001.jpg","defectType":"CRACK","severity":"CRITICAL","confidence":0.972,"bbox":{"x":132,"y":100,"w":108,"h":70},"area":7560,"position":"handle-neck"}]',2,'CRACK','CRITICAL',NULL,'REVIEWED','CONFIRMED_DEFECT','CRITICAL',2,0,'结构裂纹，不允许返工','李四','2026-06-13 10:20:00','DISPOSED','SCRAP','报废处理','质检主管','2026-06-13 10:45:00',0,NULL,NULL,NULL,NULL,'admin','2026-06-13 08:40:00','2026-06-13 08:41:00','2026-06-13 08:48:00','2026-06-13 10:45:00'),
('biz_task_ext_011','90000000-0000-4000-8000-000000000011','BATCH','BATCH-TJ-B-20260615-002','WO-TJ-B-002','PENDING_REVIEW','QA-TJ-02','王芳','轻微划伤待复核','2026-06-15 10:10:00','2026-06-15 14:00:00','COMPLETED','COMPLETED',102,'canary-2026.06-a',0.6500,'2026-06-15','天津','王芳','DEV-0010','B-002',2200,2200,2199,1,'business/tasks/ext011/original/','business/tasks/ext011/result/','business/tasks/ext011/result/result.json','["business/tasks/ext011/original/001.jpg"]','["business/tasks/ext011/result/001.jpg"]','{"normal":2199,"defect":1,"scratch":1}','[{"imageKey":"business/tasks/ext011/original/001.jpg","previewKey":"business/tasks/ext011/result/001.jpg","defectType":"SCRATCH","severity":"MINOR","confidence":0.811,"bbox":{"x":80,"y":72,"w":44,"h":31},"area":1364,"position":"handle-surface"}]',1,'SCRATCH','MINOR',NULL,'PENDING',NULL,'MINOR',0,0,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,0,NULL,NULL,NULL,NULL,'admin','2026-06-15 10:00:00','2026-06-15 10:01:00','2026-06-15 10:08:00','2026-06-15 10:10:00'),
('biz_task_ext_012','90000000-0000-4000-8000-000000000012','BATCH','BATCH-CD-E-20260615-002','WO-CD-E-002','RELEASED','QA-CD-02','陈二','复检合格放行','2026-06-12 13:00:00','2026-06-14 18:00:00','COMPLETED','COMPLETED',104,'rb-safe-2026.05',0.6000,'2026-06-12','成都','陈二','DEV-0030','E-002',2000,2000,2000,0,'business/tasks/ext012/original/','business/tasks/ext012/result/','business/tasks/ext012/result/result.json','["business/tasks/ext012/original/001.jpg"]','["business/tasks/ext012/result/001.jpg"]','{"normal":2000,"defect":0,"recheck_passed":1}','[{"imageKey":"business/tasks/ext012/original/001.jpg","previewKey":"business/tasks/ext012/result/001.jpg","defectType":"RUST","severity":"MINOR","confidence":0.603,"bbox":{"x":118,"y":96,"w":38,"h":28},"area":1064,"position":"handle-base"}]',1,'RUST','MINOR',NULL,'REVIEWED','FALSE_POSITIVE','MINOR',0,1,'复检确认合格','陈二','2026-06-14 09:20:00','DISPOSED','RELEASE','复检合格放行','质检主管','2026-06-14 09:35:00',0,'COMPLETED','返工二组','复检通过','2026-06-14 09:10:00','admin','2026-06-12 12:50:00','2026-06-12 12:51:00','2026-06-12 12:58:00','2026-06-14 09:35:00')
ON DUPLICATE KEY UPDATE
    `workflow_uuid` = VALUES(`workflow_uuid`),
    `task_type` = VALUES(`task_type`),
    `batch_no` = VALUES(`batch_no`),
    `work_order_no` = VALUES(`work_order_no`),
    `flow_status` = VALUES(`flow_status`),
    `quality_station` = VALUES(`quality_station`),
    `assignee` = VALUES(`assignee`),
    `assignment_remark` = VALUES(`assignment_remark`),
    `assigned_at` = VALUES(`assigned_at`),
    `due_at` = VALUES(`due_at`),
    `status` = VALUES(`status`),
    `stage` = VALUES(`stage`),
    `model_id` = VALUES(`model_id`),
    `model_version` = VALUES(`model_version`),
    `threshold` = VALUES(`threshold`),
    `capture_date` = VALUES(`capture_date`),
    `region` = VALUES(`region`),
    `collector` = VALUES(`collector`),
    `device_name` = VALUES(`device_name`),
    `image_folder_name` = VALUES(`image_folder_name`),
    `total_images` = VALUES(`total_images`),
    `processed_images` = VALUES(`processed_images`),
    `successful_images` = VALUES(`successful_images`),
    `failed_images` = VALUES(`failed_images`),
    `source_oss_prefix` = VALUES(`source_oss_prefix`),
    `result_oss_prefix` = VALUES(`result_oss_prefix`),
    `result_json_oss_key` = VALUES(`result_json_oss_key`),
    `original_image_keys_json` = VALUES(`original_image_keys_json`),
    `preview_image_keys_json` = VALUES(`preview_image_keys_json`),
    `statistics_json` = VALUES(`statistics_json`),
    `defect_evidence_json` = VALUES(`defect_evidence_json`),
    `defect_count` = VALUES(`defect_count`),
    `primary_defect_type` = VALUES(`primary_defect_type`),
    `max_defect_severity` = VALUES(`max_defect_severity`),
    `error_message` = VALUES(`error_message`),
    `review_status` = VALUES(`review_status`),
    `review_conclusion` = VALUES(`review_conclusion`),
    `severity_level` = VALUES(`severity_level`),
    `confirmed_defect_count` = VALUES(`confirmed_defect_count`),
    `false_positive_count` = VALUES(`false_positive_count`),
    `review_remark` = VALUES(`review_remark`),
    `reviewer` = VALUES(`reviewer`),
    `reviewed_at` = VALUES(`reviewed_at`),
    `disposition_status` = VALUES(`disposition_status`),
    `disposition_action` = VALUES(`disposition_action`),
    `disposition_remark` = VALUES(`disposition_remark`),
    `disposition_operator` = VALUES(`disposition_operator`),
    `disposed_at` = VALUES(`disposed_at`),
    `recheck_required` = VALUES(`recheck_required`),
    `rework_result` = VALUES(`rework_result`),
    `rework_operator` = VALUES(`rework_operator`),
    `rework_remark` = VALUES(`rework_remark`),
    `rework_completed_at` = VALUES(`rework_completed_at`),
    `created_by` = VALUES(`created_by`),
    `created_at` = VALUES(`created_at`),
    `started_at` = VALUES(`started_at`),
    `finished_at` = VALUES(`finished_at`),
    `updated_at` = VALUES(`updated_at`);
