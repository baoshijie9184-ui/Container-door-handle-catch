-- V11: 完善质检任务流转，增加分派、返工、复检追溯字段
ALTER TABLE `detection_task`
    ADD COLUMN `quality_station` VARCHAR(64) DEFAULT NULL COMMENT '质检工位/复核站点' AFTER `flow_status`,
    ADD COLUMN `assignee` VARCHAR(64) DEFAULT NULL COMMENT '质检责任人' AFTER `quality_station`,
    ADD COLUMN `assignment_remark` VARCHAR(500) DEFAULT NULL COMMENT '质检分派备注' AFTER `assignee`,
    ADD COLUMN `assigned_at` DATETIME DEFAULT NULL COMMENT '质检分派时间' AFTER `assignment_remark`,
    ADD COLUMN `due_at` DATETIME DEFAULT NULL COMMENT '质检截止时间' AFTER `assigned_at`,
    ADD COLUMN `rework_result` VARCHAR(64) DEFAULT NULL COMMENT '返工结果' AFTER `recheck_required`,
    ADD COLUMN `rework_operator` VARCHAR(64) DEFAULT NULL COMMENT '返工执行人' AFTER `rework_result`,
    ADD COLUMN `rework_remark` VARCHAR(1000) DEFAULT NULL COMMENT '返工备注' AFTER `rework_operator`,
    ADD COLUMN `rework_completed_at` DATETIME DEFAULT NULL COMMENT '返工完成时间' AFTER `rework_remark`;

CREATE INDEX `idx_detection_task_assignee_flow`
    ON `detection_task` (`assignee`, `flow_status`, `due_at`);

CREATE INDEX `idx_detection_task_quality_station`
    ON `detection_task` (`quality_station`, `flow_status`, `due_at`);

CREATE INDEX `idx_detection_task_due_at`
    ON `detection_task` (`due_at`);
