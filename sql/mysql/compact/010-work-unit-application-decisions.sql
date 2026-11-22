-- Existing compact monoliths. The original application and remark stay intact.
SET @ddl = IF(EXISTS(SELECT 1 FROM information_schema.columns WHERE table_schema=DATABASE()
  AND table_name='detection_work_unit' AND column_name='decision_request_id'), 'SELECT 1',
  'ALTER TABLE detection_work_unit ADD COLUMN decision_request_id CHAR(36) COLLATE utf8mb4_bin NULL, ALGORITHM=INSTANT');
PREPARE work_unit_upgrade FROM @ddl;
EXECUTE work_unit_upgrade;
DEALLOCATE PREPARE work_unit_upgrade;

SET @ddl = IF(EXISTS(SELECT 1 FROM information_schema.columns WHERE table_schema=DATABASE()
  AND table_name='detection_work_unit' AND column_name='decision_actor_user_id'), 'SELECT 1',
  'ALTER TABLE detection_work_unit ADD COLUMN decision_actor_user_id BIGINT NULL, ALGORITHM=INSTANT');
PREPARE work_unit_upgrade FROM @ddl;
EXECUTE work_unit_upgrade;
DEALLOCATE PREPARE work_unit_upgrade;

SET @ddl = IF(EXISTS(SELECT 1 FROM information_schema.columns WHERE table_schema=DATABASE()
  AND table_name='detection_work_unit' AND column_name='decision_reason'), 'SELECT 1',
  'ALTER TABLE detection_work_unit ADD COLUMN decision_reason VARCHAR(1000) COLLATE utf8mb4_0900_ai_ci NULL, ALGORITHM=INSTANT');
PREPARE work_unit_upgrade FROM @ddl;
EXECUTE work_unit_upgrade;
DEALLOCATE PREPARE work_unit_upgrade;
