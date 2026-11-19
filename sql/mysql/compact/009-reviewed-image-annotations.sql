-- Additive upgrade for existing monoliths. Old versions ignore this column.
SET @ddl = IF(EXISTS(SELECT 1 FROM information_schema.columns WHERE table_schema=DATABASE()
  AND table_name='detection_task' AND column_name='review_annotations_json'), 'SELECT 1',
  'ALTER TABLE detection_task ADD COLUMN review_annotations_json JSON NULL, ALGORITHM=INSTANT');
PREPARE annotation_upgrade FROM @ddl;
EXECUTE annotation_upgrade;
DEALLOCATE PREPARE annotation_upgrade;
