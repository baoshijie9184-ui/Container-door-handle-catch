-- V62: detection model training and measured evaluation facts. Requires model_management and V6.
-- Additive, no historical backfill. Keep columns when rolling the application back.

SET @model_fact_ddl = IF(EXISTS(SELECT 1 FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='model_management' AND column_name='training_image_count'), 'SELECT 1', 'ALTER TABLE model_management ADD COLUMN training_image_count INT NULL COMMENT ''Training source images, excluding augmentation repetitions''');
PREPARE model_fact_stmt FROM @model_fact_ddl;
EXECUTE model_fact_stmt;
DEALLOCATE PREPARE model_fact_stmt;

SET @model_fact_ddl = IF(EXISTS(SELECT 1 FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='model_management' AND column_name='training_completed_at'), 'SELECT 1', 'ALTER TABLE model_management ADD COLUMN training_completed_at DATETIME NULL COMMENT ''Training completion in UTC+8, not upload time''');
PREPARE model_fact_stmt FROM @model_fact_ddl;
EXECUTE model_fact_stmt;
DEALLOCATE PREPARE model_fact_stmt;

SET @model_fact_ddl = IF(EXISTS(SELECT 1 FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='model_management' AND column_name='evaluation_image_count'), 'SELECT 1', 'ALTER TABLE model_management ADD COLUMN evaluation_image_count INT NULL COMMENT ''Successfully evaluated images, excludes failures''');
PREPARE model_fact_stmt FROM @model_fact_ddl;
EXECUTE model_fact_stmt;
DEALLOCATE PREPARE model_fact_stmt;

SET @model_fact_ddl = IF(EXISTS(SELECT 1 FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='model_management' AND column_name='no_detection_image_count'), 'SELECT 1', 'ALTER TABLE model_management ADD COLUMN no_detection_image_count INT NULL COMMENT ''Evaluated images with zero detected objects, all categories''');
PREPARE model_fact_stmt FROM @model_fact_ddl;
EXECUTE model_fact_stmt;
DEALLOCATE PREPARE model_fact_stmt;

SET @model_fact_ddl = IF(EXISTS(SELECT 1 FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='model_management' AND column_name='inference_fps'), 'SELECT 1', 'ALTER TABLE model_management ADD COLUMN inference_fps DECIMAL(12,4) NULL COMMENT ''Measured images per second under recorded environment''');
PREPARE model_fact_stmt FROM @model_fact_ddl;
EXECUTE model_fact_stmt;
DEALLOCATE PREPARE model_fact_stmt;
