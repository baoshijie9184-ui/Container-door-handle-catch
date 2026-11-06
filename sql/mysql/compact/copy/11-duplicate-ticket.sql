-- MySQL 8.4, unverified source artifact. USE an empty compact target and stop source writers first.
-- Render __SOURCE_SCHEMA__ only after validating it as a MySQL identifier; source and target must differ.
-- The runner must stop at the first error and ROLLBACK on the same connection, never use --force.
-- The source is read-only. Preserve all 20 original fields, JSON values, NULLs, IDs and wall-clock dates.
-- This same-name domain table remains a target business table; it is never copied into workflow_instance.
CREATE TEMPORARY TABLE compact_duplicate_guard(valid INT NOT NULL CHECK(valid=1)) ENGINE=InnoDB;
INSERT INTO compact_duplicate_guard SELECT IF(DATABASE() IS NOT NULL AND BINARY DATABASE()<>BINARY '__SOURCE_SCHEMA__',1,0);
INSERT INTO compact_duplicate_guard SELECT IF(COUNT(*)=1,1,0) FROM information_schema.tables
 WHERE table_schema='__SOURCE_SCHEMA__' AND table_name='detection_duplicate_ticket' AND table_type='BASE TABLE' AND engine='InnoDB';
INSERT INTO compact_duplicate_guard SELECT IF(COUNT(*)=0,1,0) FROM detection_duplicate_ticket;
-- V15 has exactly these 20 columns. Unknown source columns require a reviewed mapping, never SELECT * truncation.
INSERT INTO compact_duplicate_guard SELECT IF(COUNT(*)=20,1,0) FROM information_schema.columns
 WHERE table_schema='__SOURCE_SCHEMA__' AND table_name='detection_duplicate_ticket';
INSERT INTO compact_duplicate_guard SELECT IF(COUNT(*)=20,1,0) FROM information_schema.columns
 WHERE table_schema=DATABASE() AND table_name='detection_duplicate_ticket';
INSERT INTO compact_duplicate_guard SELECT IF(COUNT(*)=0,1,0) FROM information_schema.columns s
 LEFT JOIN information_schema.columns t ON t.table_schema=DATABASE() AND t.table_name='detection_duplicate_ticket' AND t.column_name=s.column_name
 WHERE s.table_schema='__SOURCE_SCHEMA__' AND s.table_name='detection_duplicate_ticket'
 AND (t.column_name IS NULL OR NOT(BINARY s.column_type<=>BINARY t.column_type) OR NOT(s.is_nullable<=>t.is_nullable)
      OR NOT(s.character_set_name<=>t.character_set_name) OR NOT(s.collation_name<=>t.collation_name)
      OR NOT(s.datetime_precision<=>t.datetime_precision) OR NOT(s.generation_expression<=>t.generation_expression)
      OR NOT(BINARY s.column_default<=>BINARY t.column_default) OR NOT(BINARY s.extra<=>BINARY t.extra));
-- V15 had no FK, CHECK or trigger. Later additions need an explicit retention decision before copying.
INSERT INTO compact_duplicate_guard SELECT IF(COUNT(*)=0,1,0) FROM information_schema.table_constraints
 WHERE table_schema='__SOURCE_SCHEMA__' AND table_name='detection_duplicate_ticket' AND constraint_type IN ('FOREIGN KEY','CHECK');
INSERT INTO compact_duplicate_guard SELECT IF(COUNT(*)=0,1,0) FROM information_schema.triggers
 WHERE event_object_schema='__SOURCE_SCHEMA__' AND event_object_table='detection_duplicate_ticket';
-- The old unique ticket identity is preserved. No new uniqueness is imposed on task pairs or image hashes.
INSERT INTO compact_duplicate_guard SELECT IF(COUNT(*)=2,1,0) FROM (
 SELECT index_name,GROUP_CONCAT(column_name ORDER BY seq_in_index) AS columns_in_key,SUM(sub_part IS NOT NULL) AS prefixes
 FROM information_schema.statistics WHERE table_schema='__SOURCE_SCHEMA__' AND table_name='detection_duplicate_ticket' AND non_unique=0 GROUP BY index_name
) keys_found WHERE prefixes=0 AND ((index_name='PRIMARY' AND columns_in_key='id') OR (index_name='uk_detection_duplicate_ticket' AND columns_in_key='ticket_id'));
INSERT INTO compact_duplicate_guard SELECT IF(COUNT(DISTINCT index_name)=2,1,0) FROM information_schema.statistics
 WHERE table_schema='__SOURCE_SCHEMA__' AND table_name='detection_duplicate_ticket' AND non_unique=0;
INSERT INTO compact_duplicate_guard SELECT IF(COUNT(*)=0,1,0) FROM `__SOURCE_SCHEMA__`.detection_duplicate_ticket
 WHERE id<=0 OR version<0 OR NOT REGEXP_LIKE(sha256,'^[A-Fa-f0-9]{64}$','c')
 OR BINARY status NOT IN (BINARY 'OPEN',BINARY 'ASSIGNED',BINARY 'COMPARING',BINARY 'PENDING_APPROVAL',BINARY 'RESOLVED')
 OR (resolution IS NOT NULL AND BINARY resolution NOT IN (BINARY 'ACCEPT_LEFT',BINARY 'ACCEPT_RIGHT',BINARY 'REDETECT'))
 OR (status='RESOLVED' AND (resolution IS NULL OR approved_by IS NULL OR CHAR_LENGTH(TRIM(approved_by))=0 OR approved_at IS NULL));
-- Reserve the source AUTO_INCREMENT high-water mark before copying explicit IDs, including deleted historical IDs.
-- ALTER is deliberately outside the row-copy transaction. A failure leaves only an unused empty target; no cutover is allowed.
SET SESSION information_schema_stats_expiry=0;
SET @compact_duplicate_source_next=(SELECT AUTO_INCREMENT FROM information_schema.tables WHERE table_schema='__SOURCE_SCHEMA__' AND table_name='detection_duplicate_ticket');
INSERT INTO compact_duplicate_guard SELECT IF(@compact_duplicate_source_next IS NOT NULL AND @compact_duplicate_source_next BETWEEN 1 AND 9223372036854775807
 AND @compact_duplicate_source_next>(SELECT COALESCE(MAX(id),0) FROM `__SOURCE_SCHEMA__`.detection_duplicate_ticket),1,0);
SET @compact_duplicate_reserve_sql=CONCAT('ALTER TABLE detection_duplicate_ticket AUTO_INCREMENT=',CAST(@compact_duplicate_source_next AS CHAR));
PREPARE compact_duplicate_reserve FROM @compact_duplicate_reserve_sql;
EXECUTE compact_duplicate_reserve;
DEALLOCATE PREPARE compact_duplicate_reserve;
START TRANSACTION;
INSERT INTO detection_duplicate_ticket(id,ticket_id,sha256,left_task_id,right_task_id,left_employee_id,right_employee_id,left_folder_name,right_folder_name,
 left_images_json,right_images_json,assigned_to,comparison_result,resolution,status,approved_by,approved_at,version,created_at,updated_at)
 SELECT id,ticket_id,sha256,left_task_id,right_task_id,left_employee_id,right_employee_id,left_folder_name,right_folder_name,
 left_images_json,right_images_json,assigned_to,comparison_result,resolution,status,approved_by,approved_at,version,created_at,updated_at
 FROM `__SOURCE_SCHEMA__`.detection_duplicate_ticket ORDER BY id;
INSERT INTO compact_duplicate_guard SELECT IF((SELECT COUNT(*) FROM detection_duplicate_ticket)=(SELECT COUNT(*) FROM `__SOURCE_SCHEMA__`.detection_duplicate_ticket),1,0);
INSERT INTO compact_duplicate_guard SELECT IF(COUNT(*)=0,1,0) FROM `__SOURCE_SCHEMA__`.detection_duplicate_ticket s
 LEFT JOIN detection_duplicate_ticket t ON t.id=s.id
 WHERE t.id IS NULL OR NOT(BINARY t.ticket_id<=>BINARY s.ticket_id) OR NOT(BINARY t.sha256<=>BINARY s.sha256)
 OR NOT(BINARY t.left_task_id<=>BINARY s.left_task_id) OR NOT(BINARY t.right_task_id<=>BINARY s.right_task_id)
 OR NOT(BINARY t.left_employee_id<=>BINARY s.left_employee_id) OR NOT(BINARY t.right_employee_id<=>BINARY s.right_employee_id)
 OR NOT(BINARY t.left_folder_name<=>BINARY s.left_folder_name) OR NOT(BINARY t.right_folder_name<=>BINARY s.right_folder_name)
 OR NOT(BINARY CAST(t.left_images_json AS CHAR CHARACTER SET utf8mb4)<=>BINARY CAST(s.left_images_json AS CHAR CHARACTER SET utf8mb4))
 OR NOT(BINARY CAST(t.right_images_json AS CHAR CHARACTER SET utf8mb4)<=>BINARY CAST(s.right_images_json AS CHAR CHARACTER SET utf8mb4))
 OR NOT(BINARY t.assigned_to<=>BINARY s.assigned_to) OR NOT(BINARY t.comparison_result<=>BINARY s.comparison_result)
 OR NOT(BINARY t.resolution<=>BINARY s.resolution) OR NOT(BINARY t.status<=>BINARY s.status) OR NOT(BINARY t.approved_by<=>BINARY s.approved_by)
 OR NOT(t.approved_at<=>s.approved_at) OR NOT(t.version<=>s.version) OR NOT(t.created_at<=>s.created_at) OR NOT(t.updated_at<=>s.updated_at);
INSERT INTO compact_duplicate_guard SELECT IF(AUTO_INCREMENT=@compact_duplicate_source_next,1,0) FROM information_schema.tables
 WHERE table_schema=DATABASE() AND table_name='detection_duplicate_ticket';
COMMIT;
DROP TEMPORARY TABLE compact_duplicate_guard;
