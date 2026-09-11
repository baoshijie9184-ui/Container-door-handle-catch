-- V6: 模型 MLOps 基础字段
-- 幂等迁移：支持已有字段/索引的环境重复执行。

DELIMITER //

DROP PROCEDURE IF EXISTS add_column_if_missing//
CREATE PROCEDURE add_column_if_missing(IN p_table VARCHAR(64), IN p_column VARCHAR(64), IN p_definition TEXT)
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = p_table AND COLUMN_NAME = p_column
  ) THEN
    SET @ddl = CONCAT('ALTER TABLE `', p_table, '` ADD COLUMN ', p_definition);
    PREPARE stmt FROM @ddl;
    EXECUTE stmt;
    DEALLOCATE PREPARE stmt;
  END IF;
END//

DROP PROCEDURE IF EXISTS add_index_if_missing//
CREATE PROCEDURE add_index_if_missing(IN p_table VARCHAR(64), IN p_index VARCHAR(64), IN p_definition TEXT)
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.STATISTICS
    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = p_table AND INDEX_NAME = p_index
  ) THEN
    SET @ddl = CONCAT('ALTER TABLE `', p_table, '` ADD ', p_definition);
    PREPARE stmt FROM @ddl;
    EXECUTE stmt;
    DEALLOCATE PREPARE stmt;
  END IF;
END//

DELIMITER ;

CALL add_column_if_missing('model_management', 'mlops_status', '`mlops_status` VARCHAR(32) NOT NULL DEFAULT ''UNASSESSED'' COMMENT ''MLOps状态: UNASSESSED/EVALUATED/ROLLOUT/ROLLED_BACK'' AFTER `validation_message`');
CALL add_column_if_missing('model_management', 'evaluation_dataset', '`evaluation_dataset` VARCHAR(128) DEFAULT NULL COMMENT ''评估测试集名称'' AFTER `mlops_status`');
CALL add_column_if_missing('model_management', 'precision_score', '`precision_score` DECIMAL(8,4) DEFAULT NULL COMMENT ''精确率'' AFTER `evaluation_dataset`');
CALL add_column_if_missing('model_management', 'recall_score', '`recall_score` DECIMAL(8,4) DEFAULT NULL COMMENT ''召回率'' AFTER `precision_score`');
CALL add_column_if_missing('model_management', 'map_score', '`map_score` DECIMAL(8,4) DEFAULT NULL COMMENT ''mAP指标'' AFTER `recall_score`');
CALL add_column_if_missing('model_management', 'f1_score', '`f1_score` DECIMAL(8,4) DEFAULT NULL COMMENT ''F1指标'' AFTER `map_score`');
CALL add_column_if_missing('model_management', 'avg_inference_ms', '`avg_inference_ms` INT DEFAULT NULL COMMENT ''平均推理耗时毫秒'' AFTER `f1_score`');
CALL add_column_if_missing('model_management', 'compatibility_note', '`compatibility_note` VARCHAR(500) DEFAULT NULL COMMENT ''版本兼容性说明'' AFTER `avg_inference_ms`');
CALL add_column_if_missing('model_management', 'deployment_strategy', '`deployment_strategy` VARCHAR(32) NOT NULL DEFAULT ''FULL'' COMMENT ''部署策略: FULL/CANARY/AB_TEST/ROLLBACK'' AFTER `compatibility_note`');
CALL add_column_if_missing('model_management', 'canary_percent', '`canary_percent` INT NOT NULL DEFAULT 100 COMMENT ''灰度流量比例'' AFTER `deployment_strategy`');
CALL add_column_if_missing('model_management', 'ab_group', '`ab_group` VARCHAR(32) DEFAULT NULL COMMENT ''A/B测试分组'' AFTER `canary_percent`');
CALL add_column_if_missing('model_management', 'rollback_from_model_id', '`rollback_from_model_id` INT DEFAULT NULL COMMENT ''回滚来源模型ID'' AFTER `ab_group`');

UPDATE `model_management`
SET `mlops_status` = CASE WHEN `mlops_status` IS NULL OR `mlops_status` = '' THEN 'UNASSESSED' ELSE `mlops_status` END,
    `deployment_strategy` = CASE WHEN `deployment_strategy` IS NULL OR `deployment_strategy` = '' THEN 'FULL' ELSE `deployment_strategy` END,
    `canary_percent` = COALESCE(`canary_percent`, 100);

CALL add_index_if_missing('model_management', 'idx_model_management_mlops_status', 'INDEX `idx_model_management_mlops_status` (`mlops_status`)');
CALL add_index_if_missing('model_management', 'idx_model_management_deployment_strategy', 'INDEX `idx_model_management_deployment_strategy` (`deployment_strategy`)');

DROP PROCEDURE IF EXISTS add_column_if_missing;
DROP PROCEDURE IF EXISTS add_index_if_missing;
