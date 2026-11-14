-- Generated explicit legacy-clock protocol by author_legacy_clock_copy.py.
-- validation_wall_offset is ONLY a zero-shift wall-value validator when unresolved.
-- It is never persisted as a source offset or used to manufacture UTC.
SET @compact_source_clock_unresolved=BINARY '__SOURCE_REPORT_OFFSET__'=BINARY 'UNRESOLVED';
SET @compact_validation_wall_offset=IF(@compact_source_clock_unresolved,'+00:00','__SOURCE_REPORT_OFFSET__');
CREATE TEMPORARY TABLE compact_report_guard(valid INT NOT NULL CHECK(valid=1));
START TRANSACTION;
INSERT INTO compact_report_guard SELECT IF(NOT @compact_source_clock_unresolved OR REGEXP_LIKE('__SOURCE_SNAPSHOT_SHA256__','^[a-f0-9]{64}$','c'),1,0);
CREATE TEMPORARY TABLE compact_report_columns(table_name VARCHAR(64),column_name VARCHAR(64),position_no INT,column_type VARCHAR(64),nullable VARCHAR(3),collation_name VARCHAR(64),default_value VARCHAR(64),extra VARCHAR(64),PRIMARY KEY(table_name,column_name)) ENGINE=InnoDB;
INSERT INTO compact_report_columns VALUES
('detection_quality_report','id','1','bigint','NO',NULL,NULL,'auto_increment'),
('detection_quality_report','report_id','2','varchar(64)','NO','utf8mb4_unicode_ci',NULL,''),
('detection_quality_report','previous_report_id','3','varchar(64)','YES','utf8mb4_unicode_ci',NULL,''),
('detection_quality_report','owner_user_id','4','bigint','NO',NULL,NULL,''),
('detection_quality_report','owner_username','5','varchar(50)','NO','utf8mb4_unicode_ci',NULL,''),
('detection_quality_report','task_id','6','varchar(128)','NO','utf8mb4_unicode_ci',NULL,''),
('detection_quality_report','title','7','varchar(120)','NO','utf8mb4_unicode_ci',NULL,''),
('detection_quality_report','narrative','8','text','NO','utf8mb4_unicode_ci',NULL,''),
('detection_quality_report','status','9','varchar(20)','NO','utf8mb4_unicode_ci',NULL,''),
('detection_quality_report','version','10','int','NO',NULL,NULL,''),
('detection_quality_report','source_json','11','mediumtext','NO','utf8mb4_unicode_ci',NULL,''),
('detection_quality_report','source_sha256','12','char(64)','NO','utf8mb4_unicode_ci',NULL,''),
('detection_quality_report','snapshot_sha256','13','char(64)','YES','utf8mb4_unicode_ci',NULL,''),
('detection_quality_report','submitted_at','14','datetime','YES',NULL,NULL,''),
('detection_quality_report','decided_at','15','datetime','YES',NULL,NULL,''),
('detection_quality_report','decider_user_id','16','bigint','YES',NULL,NULL,''),
('detection_quality_report','decider_username','17','varchar(50)','YES','utf8mb4_unicode_ci',NULL,''),
('detection_quality_report','decision_reason','18','varchar(500)','YES','utf8mb4_unicode_ci',NULL,''),
('detection_quality_report','created_at','19','datetime','NO',NULL,NULL,''),
('detection_quality_report','updated_at','20','datetime','NO',NULL,NULL,''),
('detection_report_audit','id','1','bigint','NO',NULL,NULL,'auto_increment'),
('detection_report_audit','report_id','2','varchar(64)','NO','utf8mb4_unicode_ci',NULL,''),
('detection_report_audit','actor_user_id','3','bigint','NO',NULL,NULL,''),
('detection_report_audit','actor_username','4','varchar(50)','NO','utf8mb4_unicode_ci',NULL,''),
('detection_report_audit','action','5','varchar(24)','NO','utf8mb4_unicode_ci',NULL,''),
('detection_report_audit','before_status','6','varchar(20)','YES','utf8mb4_unicode_ci',NULL,''),
('detection_report_audit','after_status','7','varchar(20)','NO','utf8mb4_unicode_ci',NULL,''),
('detection_report_audit','report_version','8','int','NO',NULL,NULL,''),
('detection_report_audit','reason','9','varchar(500)','YES','utf8mb4_unicode_ci',NULL,''),
('detection_report_audit','snapshot_sha256','10','char(64)','YES','utf8mb4_unicode_ci',NULL,''),
('detection_report_audit','created_at','11','datetime','NO',NULL,NULL,''),
('detection_report_command','actor_user_id','1','bigint','NO',NULL,NULL,''),
('detection_report_command','request_id','2','varchar(64)','NO','utf8mb4_unicode_ci',NULL,''),
('detection_report_command','command_sha256','3','char(64)','NO','utf8mb4_unicode_ci',NULL,''),
('detection_report_command','report_id','4','varchar(64)','NO','utf8mb4_unicode_ci',NULL,''),
('detection_report_command','response_json','5','mediumtext','NO','utf8mb4_unicode_ci',NULL,''),
('detection_report_command','created_at','6','datetime','NO',NULL,NULL,''),
('detection_report_confirmation','token','1','char(64)','NO','utf8mb4_unicode_ci',NULL,''),
('detection_report_confirmation','report_id','2','varchar(64)','NO','utf8mb4_unicode_ci',NULL,''),
('detection_report_confirmation','actor_user_id','3','bigint','NO',NULL,NULL,''),
('detection_report_confirmation','report_version','4','int','NO',NULL,NULL,''),
('detection_report_confirmation','snapshot_sha256','5','char(64)','NO','utf8mb4_unicode_ci',NULL,''),
('detection_report_confirmation','decision_sha256','6','char(64)','NO','utf8mb4_unicode_ci',NULL,''),
('detection_report_confirmation','expires_at','7','datetime','NO',NULL,NULL,''),
('detection_report_confirmation','used_at','8','datetime','YES',NULL,NULL,''),
('detection_report_outbox','event_id','1','varchar(64)','NO','utf8mb4_unicode_ci',NULL,''),
('detection_report_outbox','report_id','2','varchar(64)','NO','utf8mb4_unicode_ci',NULL,''),
('detection_report_outbox','event_type','3','varchar(80)','NO','utf8mb4_unicode_ci',NULL,''),
('detection_report_outbox','payload_json','4','text','NO','utf8mb4_unicode_ci',NULL,''),
('detection_report_outbox','delivery_status','5','varchar(20)','NO','utf8mb4_unicode_ci','PENDING',''),
('detection_report_outbox','created_at','6','datetime','NO',NULL,NULL,''),
('detection_report_outbox','attempts','7','int','NO',NULL,'0',''),
('detection_report_outbox','next_attempt_at','8','datetime','NO',NULL,'current_timestamp','default_generated'),
('detection_report_outbox','lease_token','9','varchar(64)','YES','utf8mb4_unicode_ci',NULL,''),
('detection_report_outbox','lease_expires_at','10','datetime','YES',NULL,NULL,''),
('detection_report_outbox','delivered_at','11','datetime','YES',NULL,NULL,''),
('detection_report_outbox','last_error_code','12','varchar(40)','YES','utf8mb4_unicode_ci',NULL,''),
('detection_report_agent_origin','actor_user_id','1','bigint','NO',NULL,NULL,''),
('detection_report_agent_origin','request_id','2','varchar(64)','NO','utf8mb4_unicode_ci',NULL,''),
('detection_report_agent_origin','report_id','3','varchar(64)','NO','utf8mb4_unicode_ci',NULL,''),
('detection_report_agent_origin','report_version','4','int','NO',NULL,NULL,''),
('detection_report_agent_origin','run_id','5','varchar(128)','NO','utf8mb4_unicode_ci',NULL,''),
('detection_report_agent_origin','call_id','6','varchar(160)','NO','utf8mb4_unicode_ci',NULL,''),
('detection_report_agent_origin','tool_name','7','varchar(64)','NO','utf8mb4_unicode_ci',NULL,''),
('detection_report_agent_origin','created_at','8','datetime','NO',NULL,NULL,''),
('detection_report_event_receipt','event_id','1','varchar(64)','NO','utf8mb4_unicode_ci',NULL,''),
('detection_report_event_receipt','report_id','2','varchar(64)','NO','utf8mb4_unicode_ci',NULL,''),
('detection_report_event_receipt','event_type','3','varchar(80)','NO','utf8mb4_unicode_ci',NULL,''),
('detection_report_event_receipt','report_version','4','int','NO',NULL,NULL,''),
('detection_report_event_receipt','payload_sha256','5','char(64)','NO','utf8mb4_unicode_ci',NULL,''),
('detection_report_event_receipt','consumed_at','6','datetime','NO',NULL,NULL,''),
('detection_report_event_state','report_id','1','varchar(64)','NO','utf8mb4_unicode_ci',NULL,''),
('detection_report_event_state','last_version','2','int','NO',NULL,NULL,''),
('detection_report_event_state','status','3','varchar(20)','NO','utf8mb4_unicode_ci',NULL,''),
('detection_report_event_state','last_event_id','4','varchar(64)','NO','utf8mb4_unicode_ci',NULL,''),
('detection_report_event_state','updated_at','5','datetime','NO',NULL,NULL,'');
CREATE TEMPORARY TABLE compact_report_indexes(table_name VARCHAR(64),index_name VARCHAR(64),position_no INT,column_name VARCHAR(64),non_unique INT,PRIMARY KEY(table_name,index_name,position_no)) ENGINE=InnoDB;
INSERT INTO compact_report_indexes VALUES
('detection_quality_report','PRIMARY','1','id','0'),
('detection_quality_report','uk_quality_report_id','1','report_id','0'),
('detection_quality_report','idx_quality_report_owner','1','owner_user_id','1'),
('detection_quality_report','idx_quality_report_owner','2','id','1'),
('detection_quality_report','idx_quality_report_status','1','status','1'),
('detection_quality_report','idx_quality_report_status','2','id','1'),
('detection_quality_report','idx_quality_report_task','1','task_id','1'),
('detection_report_audit','PRIMARY','1','id','0'),
('detection_report_audit','idx_report_audit_report','1','report_id','1'),
('detection_report_audit','idx_report_audit_report','2','id','1'),
('detection_report_command','PRIMARY','1','actor_user_id','0'),
('detection_report_command','PRIMARY','2','request_id','0'),
('detection_report_confirmation','PRIMARY','1','token','0'),
('detection_report_confirmation','idx_report_confirmation_expiry','1','expires_at','1'),
('detection_report_outbox','PRIMARY','1','event_id','0'),
('detection_report_outbox','idx_report_outbox_pending','1','delivery_status','1'),
('detection_report_outbox','idx_report_outbox_pending','2','created_at','1'),
('detection_report_outbox','idx_report_event_due','1','delivery_status','1'),
('detection_report_outbox','idx_report_event_due','2','next_attempt_at','1'),
('detection_report_outbox','idx_report_event_lease','1','delivery_status','1'),
('detection_report_outbox','idx_report_event_lease','2','lease_expires_at','1'),
('detection_report_outbox','idx_report_event_report','1','report_id','1'),
('detection_report_agent_origin','PRIMARY','1','actor_user_id','0'),
('detection_report_agent_origin','PRIMARY','2','request_id','0'),
('detection_report_agent_origin','idx_report_origin_report','1','report_id','1'),
('detection_report_agent_origin','idx_report_origin_report','2','report_version','1'),
('detection_report_agent_origin','idx_report_origin_run','1','run_id','1'),
('detection_report_event_receipt','PRIMARY','1','event_id','0'),
('detection_report_event_receipt','uk_report_event_version','1','report_id','0'),
('detection_report_event_receipt','uk_report_event_version','2','report_version','0'),
('detection_report_event_state','PRIMARY','1','report_id','0');
INSERT INTO compact_report_guard SELECT IF((SELECT COUNT(DISTINCT privilege_type) FROM information_schema.schema_privileges WHERE BINARY table_schema=BINARY '__SOURCE_SCHEMA__' AND privilege_type IN ('SELECT','TRIGGER') AND grantee=CONCAT(QUOTE(SUBSTRING_INDEX(CURRENT_USER(),'@',1)),'@',QUOTE(SUBSTRING_INDEX(CURRENT_USER(),'@',-1))))=2,1,0);
INSERT INTO compact_report_guard SELECT IF((SELECT COUNT(*) FROM information_schema.tables WHERE BINARY table_schema=BINARY '__SOURCE_SCHEMA__' AND table_name IN ('detection_quality_report','detection_report_audit','detection_report_command','detection_report_confirmation','detection_report_outbox','detection_report_agent_origin','detection_report_event_receipt','detection_report_event_state') AND table_type='BASE TABLE' AND engine='InnoDB' AND BINARY table_collation=BINARY 'utf8mb4_unicode_ci')=8,1,0);
INSERT INTO compact_report_guard SELECT IF(NOT EXISTS(SELECT 1 FROM information_schema.columns a LEFT JOIN compact_report_columns e ON BINARY e.table_name=BINARY a.table_name AND BINARY e.column_name=BINARY a.column_name WHERE BINARY a.table_schema=BINARY '__SOURCE_SCHEMA__' AND a.table_name IN ('detection_quality_report','detection_report_audit','detection_report_command','detection_report_confirmation','detection_report_outbox','detection_report_agent_origin','detection_report_event_receipt','detection_report_event_state') AND e.column_name IS NULL),1,0);
INSERT INTO compact_report_guard SELECT IF(NOT EXISTS(SELECT 1 FROM compact_report_columns e LEFT JOIN information_schema.columns a ON BINARY a.table_schema=BINARY '__SOURCE_SCHEMA__' AND BINARY a.table_name=BINARY e.table_name AND BINARY a.column_name=BINARY e.column_name WHERE a.column_name IS NULL OR a.ordinal_position<>e.position_no OR NOT(BINARY LOWER(a.column_type)<=>BINARY e.column_type) OR NOT(BINARY a.is_nullable<=>BINARY e.nullable) OR NOT(BINARY a.collation_name<=>BINARY e.collation_name) OR NOT(BINARY a.character_set_name<=>BINARY IF(e.collation_name IS NULL,NULL,'utf8mb4')) OR NOT(BINARY (CASE WHEN e.extra='default_generated' THEN REPLACE(LOWER(a.column_default),'()','') ELSE a.column_default END)<=>BINARY e.default_value) OR NOT(BINARY LOWER(a.extra)<=>BINARY e.extra) OR a.generation_expression<>''),1,0);
INSERT INTO compact_report_guard SELECT IF(NOT EXISTS(SELECT 1 FROM information_schema.statistics a LEFT JOIN compact_report_indexes e ON BINARY e.table_name=BINARY a.table_name AND BINARY e.index_name=BINARY a.index_name AND e.position_no=a.seq_in_index WHERE BINARY a.table_schema=BINARY '__SOURCE_SCHEMA__' AND a.table_name IN ('detection_quality_report','detection_report_audit','detection_report_command','detection_report_confirmation','detection_report_outbox','detection_report_agent_origin','detection_report_event_receipt','detection_report_event_state') AND e.index_name IS NULL),1,0);
INSERT INTO compact_report_guard SELECT IF(NOT EXISTS(SELECT 1 FROM compact_report_indexes e LEFT JOIN information_schema.statistics a ON BINARY a.table_schema=BINARY '__SOURCE_SCHEMA__' AND BINARY a.table_name=BINARY e.table_name AND BINARY a.index_name=BINARY e.index_name AND a.seq_in_index=e.position_no WHERE a.index_name IS NULL OR NOT(BINARY a.column_name<=>BINARY e.column_name) OR a.non_unique<>e.non_unique OR a.sub_part IS NOT NULL OR a.expression IS NOT NULL OR a.index_type<>'BTREE' OR a.collation<>'A' OR a.is_visible<>'YES'),1,0);
INSERT INTO compact_report_guard SELECT IF(NOT EXISTS(SELECT 1 FROM information_schema.triggers WHERE BINARY event_object_schema=BINARY '__SOURCE_SCHEMA__' AND event_object_table IN ('detection_quality_report','detection_report_audit','detection_report_command','detection_report_confirmation','detection_report_outbox','detection_report_agent_origin','detection_report_event_receipt','detection_report_event_state')),1,0);
INSERT INTO compact_report_guard SELECT IF(NOT EXISTS(SELECT 1 FROM information_schema.table_constraints WHERE BINARY table_schema=BINARY '__SOURCE_SCHEMA__' AND table_name IN ('detection_quality_report','detection_report_audit','detection_report_command','detection_report_confirmation','detection_report_outbox','detection_report_agent_origin','detection_report_event_receipt','detection_report_event_state') AND constraint_type IN ('FOREIGN KEY','CHECK')),1,0);
DROP TEMPORARY TABLE compact_report_indexes;
DROP TEMPORARY TABLE compact_report_columns;
INSERT INTO compact_report_guard SELECT IF(DATABASE() IS NOT NULL AND BINARY DATABASE()<>BINARY '__SOURCE_SCHEMA__'
 AND @@FOREIGN_KEY_CHECKS=1 AND @@SESSION.sql_mode REGEXP '(^|,)(STRICT_TRANS_TABLES|STRICT_ALL_TABLES)(,|$)',1,0);
INSERT INTO compact_report_guard SELECT IF(REGEXP_LIKE(@compact_validation_wall_offset,'^[+-][0-9]{2}:[0-9]{2}$','c') AND CONVERT_TZ('2026-01-01',@compact_validation_wall_offset,'+00:00') IS NOT NULL,1,0);
INSERT INTO compact_report_guard SELECT NOT EXISTS(SELECT 1 FROM `__SOURCE_SCHEMA__`.detection_report_command s WHERE (s.created_at IS NOT NULL AND (CONVERT_TZ(s.created_at,@compact_validation_wall_offset,'+00:00') IS NULL OR NOT(TIMESTAMPDIFF(MICROSECOND,CONVERT_TZ(s.created_at,@compact_validation_wall_offset,'+00:00'),s.created_at)<=>((IF(LEFT(@compact_validation_wall_offset,1)='-',-1,1)*(CAST(SUBSTRING(@compact_validation_wall_offset,2,2) AS SIGNED)*3600+CAST(SUBSTRING(@compact_validation_wall_offset,5,2) AS SIGNED)*60))*1000000)))));
INSERT INTO compact_report_guard SELECT NOT EXISTS(SELECT 1 FROM `__SOURCE_SCHEMA__`.detection_report_confirmation s WHERE (s.expires_at IS NOT NULL AND (CONVERT_TZ(s.expires_at,@compact_validation_wall_offset,'+00:00') IS NULL OR NOT(TIMESTAMPDIFF(MICROSECOND,CONVERT_TZ(s.expires_at,@compact_validation_wall_offset,'+00:00'),s.expires_at)<=>((IF(LEFT(@compact_validation_wall_offset,1)='-',-1,1)*(CAST(SUBSTRING(@compact_validation_wall_offset,2,2) AS SIGNED)*3600+CAST(SUBSTRING(@compact_validation_wall_offset,5,2) AS SIGNED)*60))*1000000)))) OR (s.used_at IS NOT NULL AND (CONVERT_TZ(s.used_at,@compact_validation_wall_offset,'+00:00') IS NULL OR NOT(TIMESTAMPDIFF(MICROSECOND,CONVERT_TZ(s.used_at,@compact_validation_wall_offset,'+00:00'),s.used_at)<=>((IF(LEFT(@compact_validation_wall_offset,1)='-',-1,1)*(CAST(SUBSTRING(@compact_validation_wall_offset,2,2) AS SIGNED)*3600+CAST(SUBSTRING(@compact_validation_wall_offset,5,2) AS SIGNED)*60))*1000000)))));
INSERT INTO compact_report_guard SELECT NOT EXISTS(SELECT 1 FROM `__SOURCE_SCHEMA__`.detection_report_outbox s WHERE (s.created_at IS NOT NULL AND (CONVERT_TZ(s.created_at,@compact_validation_wall_offset,'+00:00') IS NULL OR NOT(TIMESTAMPDIFF(MICROSECOND,CONVERT_TZ(s.created_at,@compact_validation_wall_offset,'+00:00'),s.created_at)<=>((IF(LEFT(@compact_validation_wall_offset,1)='-',-1,1)*(CAST(SUBSTRING(@compact_validation_wall_offset,2,2) AS SIGNED)*3600+CAST(SUBSTRING(@compact_validation_wall_offset,5,2) AS SIGNED)*60))*1000000)))) OR (s.next_attempt_at IS NOT NULL AND (CONVERT_TZ(s.next_attempt_at,@compact_validation_wall_offset,'+00:00') IS NULL OR NOT(TIMESTAMPDIFF(MICROSECOND,CONVERT_TZ(s.next_attempt_at,@compact_validation_wall_offset,'+00:00'),s.next_attempt_at)<=>((IF(LEFT(@compact_validation_wall_offset,1)='-',-1,1)*(CAST(SUBSTRING(@compact_validation_wall_offset,2,2) AS SIGNED)*3600+CAST(SUBSTRING(@compact_validation_wall_offset,5,2) AS SIGNED)*60))*1000000)))) OR (s.lease_expires_at IS NOT NULL AND (CONVERT_TZ(s.lease_expires_at,@compact_validation_wall_offset,'+00:00') IS NULL OR NOT(TIMESTAMPDIFF(MICROSECOND,CONVERT_TZ(s.lease_expires_at,@compact_validation_wall_offset,'+00:00'),s.lease_expires_at)<=>((IF(LEFT(@compact_validation_wall_offset,1)='-',-1,1)*(CAST(SUBSTRING(@compact_validation_wall_offset,2,2) AS SIGNED)*3600+CAST(SUBSTRING(@compact_validation_wall_offset,5,2) AS SIGNED)*60))*1000000)))) OR (s.delivered_at IS NOT NULL AND (CONVERT_TZ(s.delivered_at,@compact_validation_wall_offset,'+00:00') IS NULL OR NOT(TIMESTAMPDIFF(MICROSECOND,CONVERT_TZ(s.delivered_at,@compact_validation_wall_offset,'+00:00'),s.delivered_at)<=>((IF(LEFT(@compact_validation_wall_offset,1)='-',-1,1)*(CAST(SUBSTRING(@compact_validation_wall_offset,2,2) AS SIGNED)*3600+CAST(SUBSTRING(@compact_validation_wall_offset,5,2) AS SIGNED)*60))*1000000)))));
INSERT INTO compact_report_guard SELECT NOT EXISTS(SELECT 1 FROM `__SOURCE_SCHEMA__`.detection_report_event_state s WHERE (s.updated_at IS NOT NULL AND (CONVERT_TZ(s.updated_at,@compact_validation_wall_offset,'+00:00') IS NULL OR NOT(TIMESTAMPDIFF(MICROSECOND,CONVERT_TZ(s.updated_at,@compact_validation_wall_offset,'+00:00'),s.updated_at)<=>((IF(LEFT(@compact_validation_wall_offset,1)='-',-1,1)*(CAST(SUBSTRING(@compact_validation_wall_offset,2,2) AS SIGNED)*3600+CAST(SUBSTRING(@compact_validation_wall_offset,5,2) AS SIGNED)*60))*1000000)))));
INSERT INTO compact_report_guard SELECT NOT EXISTS(SELECT 1 FROM `__SOURCE_SCHEMA__`.detection_report_event_receipt s WHERE (s.consumed_at IS NOT NULL AND (CONVERT_TZ(s.consumed_at,@compact_validation_wall_offset,'+00:00') IS NULL OR NOT(TIMESTAMPDIFF(MICROSECOND,CONVERT_TZ(s.consumed_at,@compact_validation_wall_offset,'+00:00'),s.consumed_at)<=>((IF(LEFT(@compact_validation_wall_offset,1)='-',-1,1)*(CAST(SUBSTRING(@compact_validation_wall_offset,2,2) AS SIGNED)*3600+CAST(SUBSTRING(@compact_validation_wall_offset,5,2) AS SIGNED)*60))*1000000)))));
INSERT INTO compact_report_guard SELECT NOT EXISTS(SELECT 1 FROM `__SOURCE_SCHEMA__`.detection_report_audit s WHERE (s.created_at IS NOT NULL AND (CONVERT_TZ(s.created_at,@compact_validation_wall_offset,'+00:00') IS NULL OR NOT(TIMESTAMPDIFF(MICROSECOND,CONVERT_TZ(s.created_at,@compact_validation_wall_offset,'+00:00'),s.created_at)<=>((IF(LEFT(@compact_validation_wall_offset,1)='-',-1,1)*(CAST(SUBSTRING(@compact_validation_wall_offset,2,2) AS SIGNED)*3600+CAST(SUBSTRING(@compact_validation_wall_offset,5,2) AS SIGNED)*60))*1000000)))));
INSERT INTO compact_report_guard SELECT NOT EXISTS(SELECT 1 FROM `__SOURCE_SCHEMA__`.detection_report_agent_origin s WHERE (s.created_at IS NOT NULL AND (CONVERT_TZ(s.created_at,@compact_validation_wall_offset,'+00:00') IS NULL OR NOT(TIMESTAMPDIFF(MICROSECOND,CONVERT_TZ(s.created_at,@compact_validation_wall_offset,'+00:00'),s.created_at)<=>((IF(LEFT(@compact_validation_wall_offset,1)='-',-1,1)*(CAST(SUBSTRING(@compact_validation_wall_offset,2,2) AS SIGNED)*3600+CAST(SUBSTRING(@compact_validation_wall_offset,5,2) AS SIGNED)*60))*1000000)))));
INSERT INTO compact_report_guard SELECT IF(CONVERT_TZ('2026-01-01',@compact_validation_wall_offset,'+00:00') IS NOT NULL,1,0);
INSERT INTO compact_report_guard SELECT IF(COUNT(*)=0,1,0) FROM workflow_instance WHERE kind IN ('REPORT_COMMAND','REPORT_CONFIRMATION','REPORT_DELIVERY','REPORT_CONSUMPTION','REPORT_AGENT_ORIGIN');
INSERT INTO compact_report_guard SELECT IF(COUNT(*)=0,1,0) FROM audit_event WHERE kind='QUALITY_REPORT';
INSERT INTO compact_report_guard SELECT IF(COUNT(*)=0,1,0) FROM runtime_state WHERE namespace='REPORT_EVENT_STATE';
INSERT INTO compact_report_guard SELECT IF(COUNT(*)=0,1,0) FROM `__SOURCE_SCHEMA__`.detection_quality_report r
 LEFT JOIN quality_report q ON BINARY q.report_id=BINARY r.report_id
 WHERE q.id IS NULL OR NOT(q.owner_user_id<=>r.owner_user_id) OR NOT(q.version<=>r.version) OR COALESCE(q.owner_user_id,0)<=0
 OR NOT COALESCE(REGEXP_LIKE(r.report_id,'^qr-[a-f0-9]{8}(-[a-f0-9]{4}){3}-[a-f0-9]{12}$','c'),FALSE);
INSERT INTO compact_report_guard SELECT IF(COUNT(*)=0,1,0) FROM `__SOURCE_SCHEMA__`.detection_report_command c
 LEFT JOIN quality_report q ON BINARY q.report_id=BINARY c.report_id
 WHERE q.id IS NULL OR COALESCE(c.actor_user_id,0)<=0 OR NOT COALESCE(REGEXP_LIKE(c.command_sha256,'^[a-f0-9]{64}$','c'),FALSE)
 OR NOT COALESCE(REGEXP_LIKE(c.request_id,'^[A-Za-z0-9_-]{8,64}$','c'),FALSE)
 OR COALESCE(JSON_VALID(c.response_json),0)<>1 OR COALESCE(CHAR_LENGTH(c.response_json),0) NOT BETWEEN 1 AND 2000000
 OR CONVERT_TZ(c.created_at,@compact_validation_wall_offset,'+00:00') IS NULL;
INSERT INTO compact_report_guard SELECT IF(COUNT(*)=0,1,0) FROM `__SOURCE_SCHEMA__`.detection_report_command c
 WHERE COALESCE(JSON_TYPE(CAST(c.response_json AS JSON)),'NULL')<>'OBJECT'
 OR COALESCE(JSON_TYPE(JSON_EXTRACT(c.response_json,'$.reportId')),'NULL')<>'STRING'
 OR NOT (BINARY JSON_UNQUOTE(JSON_EXTRACT(c.response_json,'$.reportId'))<=>BINARY c.report_id)
 OR COALESCE(JSON_TYPE(JSON_EXTRACT(c.response_json,'$.version')),'NULL')<>'INTEGER'
 OR COALESCE(JSON_TYPE(JSON_EXTRACT(c.response_json,'$.ownerUserId')),'NULL')<>'INTEGER'
 OR COALESCE(JSON_TYPE(JSON_EXTRACT(c.response_json,'$.ownerUsername')),'NULL')<>'STRING'
 OR COALESCE(JSON_TYPE(JSON_EXTRACT(c.response_json,'$.taskId')),'NULL')<>'STRING'
 OR COALESCE(JSON_TYPE(JSON_EXTRACT(c.response_json,'$.title')),'NULL')<>'STRING'
 OR COALESCE(JSON_TYPE(JSON_EXTRACT(c.response_json,'$.narrative')),'NULL')<>'STRING'
 OR COALESCE(JSON_TYPE(JSON_EXTRACT(c.response_json,'$.status')),'NULL')<>'STRING'
 OR COALESCE(JSON_TYPE(JSON_EXTRACT(c.response_json,'$.source')),'NULL')<>'OBJECT'
 OR COALESCE(JSON_TYPE(JSON_EXTRACT(c.response_json,'$.sourceSha256')),'NULL')<>'STRING'

 OR COALESCE(JSON_TYPE(JSON_EXTRACT(c.response_json,'$.createdAt')),'NULL') NOT IN ('STRING','ARRAY')
 OR COALESCE(JSON_TYPE(JSON_EXTRACT(c.response_json,'$.updatedAt')),'NULL') NOT IN ('STRING','ARRAY');
INSERT INTO compact_report_guard SELECT IF(COUNT(*)=0,1,0) FROM `__SOURCE_SCHEMA__`.detection_report_command c
 JOIN quality_report q ON BINARY q.report_id=BINARY c.report_id
 WHERE CAST(JSON_UNQUOTE(JSON_EXTRACT(c.response_json,'$.version')) AS DECIMAL(20,0)) NOT BETWEEN 1 AND 2147483647
 OR CAST(JSON_UNQUOTE(JSON_EXTRACT(c.response_json,'$.version')) AS DECIMAL(20,0))>q.version
 OR NOT(CAST(JSON_UNQUOTE(JSON_EXTRACT(c.response_json,'$.ownerUserId')) AS DECIMAL(20,0))<=>q.owner_user_id)
 OR NOT(BINARY JSON_UNQUOTE(JSON_EXTRACT(c.response_json,'$.taskId'))<=>BINARY q.task_id)
 OR BINARY JSON_UNQUOTE(JSON_EXTRACT(c.response_json,'$.status')) NOT IN (BINARY 'DRAFT',BINARY 'SUBMITTED',BINARY 'WITHDRAWN',BINARY 'APPROVED',BINARY 'REJECTED')
 OR NOT REGEXP_LIKE(JSON_UNQUOTE(JSON_EXTRACT(c.response_json,'$.sourceSha256')),'^[a-f0-9]{64}$','c');
INSERT INTO compact_report_guard SELECT IF(COUNT(*)=0,1,0) FROM `__SOURCE_SCHEMA__`.detection_report_confirmation c
 LEFT JOIN quality_report q ON BINARY q.report_id=BINARY c.report_id
 WHERE q.id IS NULL OR COALESCE(c.actor_user_id,0)<=0 OR COALESCE(c.report_version,0)<1 OR c.report_version>q.version
 OR NOT COALESCE(REGEXP_LIKE(c.snapshot_sha256,'^[a-f0-9]{64}$','c'),FALSE)
 OR NOT COALESCE(REGEXP_LIKE(c.decision_sha256,'^[a-f0-9]{64}$','c'),FALSE) OR NOT COALESCE(REGEXP_LIKE(c.token,'^[a-f0-9]{64}$','c'),FALSE)
 OR CONVERT_TZ(c.expires_at,@compact_validation_wall_offset,'+00:00') IS NULL
 OR (c.used_at IS NOT NULL AND (CONVERT_TZ(c.used_at,@compact_validation_wall_offset,'+00:00') IS NULL OR c.used_at>=c.expires_at));
INSERT INTO compact_report_guard SELECT IF(COUNT(*)=0,1,0) FROM `__SOURCE_SCHEMA__`.detection_report_agent_origin o
 LEFT JOIN quality_report q ON BINARY q.report_id=BINARY o.report_id
 WHERE q.id IS NULL OR COALESCE(o.actor_user_id,0)<=0 OR COALESCE(o.report_version,0)<1 OR o.report_version>q.version
 OR NOT COALESCE(REGEXP_LIKE(o.request_id,'^[A-Za-z0-9_-]{8,64}$','c'),FALSE)
 OR NOT COALESCE(REGEXP_LIKE(o.run_id,'^[A-Za-z0-9_:.-]{1,128}$','c'),FALSE)
 OR NOT COALESCE(REGEXP_LIKE(o.call_id,'^[A-Za-z0-9_:.-]{1,160}$','c'),FALSE)
 OR COALESCE(BINARY o.tool_name,BINARY '') NOT IN (BINARY 'create_report_draft',BINARY 'edit_report_draft')
 OR CONVERT_TZ(o.created_at,@compact_validation_wall_offset,'+00:00') IS NULL;
INSERT INTO compact_report_guard SELECT IF(COUNT(*)=0,1,0) FROM `__SOURCE_SCHEMA__`.detection_report_outbox e
 LEFT JOIN quality_report q ON BINARY q.report_id=BINARY e.report_id
 WHERE q.id IS NULL OR COALESCE(JSON_VALID(e.payload_json),0)<>1 OR COALESCE(CHAR_LENGTH(e.payload_json),0) NOT BETWEEN 1 AND 4096
 OR COALESCE(e.attempts,-1)<0 OR NOT COALESCE(REGEXP_LIKE(e.event_id,'^[a-f0-9]{8}(-[a-f0-9]{4}){3}-[a-f0-9]{12}$','c'),FALSE)
 OR COALESCE(BINARY e.delivery_status,BINARY '') NOT IN (BINARY 'PENDING',BINARY 'RETRY',BINARY 'PROCESSING',BINARY 'DELIVERED',BINARY 'FAILED')
 OR (e.delivery_status='PROCESSING' AND (e.lease_token IS NULL OR e.lease_expires_at IS NULL))
 OR (e.delivery_status<>'PROCESSING' AND (e.lease_token IS NOT NULL OR e.lease_expires_at IS NOT NULL))
 OR (e.delivery_status='DELIVERED' AND e.delivered_at IS NULL) OR (e.delivery_status<>'DELIVERED' AND e.delivered_at IS NOT NULL)
 OR (e.lease_token IS NOT NULL AND CHAR_LENGTH(e.lease_token)=0)
 OR CONVERT_TZ(e.created_at,@compact_validation_wall_offset,'+00:00') IS NULL
 OR CONVERT_TZ(e.next_attempt_at,@compact_validation_wall_offset,'+00:00') IS NULL
 OR (e.lease_expires_at IS NOT NULL AND CONVERT_TZ(e.lease_expires_at,@compact_validation_wall_offset,'+00:00') IS NULL)
 OR (e.delivered_at IS NOT NULL AND CONVERT_TZ(e.delivered_at,@compact_validation_wall_offset,'+00:00') IS NULL);
INSERT INTO compact_report_guard SELECT IF(COUNT(*)=0,1,0) FROM `__SOURCE_SCHEMA__`.detection_report_outbox e
 WHERE COALESCE(JSON_TYPE(CAST(e.payload_json AS JSON)),'NULL')<>'OBJECT' OR JSON_LENGTH(e.payload_json)<>6
 OR COALESCE(JSON_TYPE(JSON_EXTRACT(e.payload_json,'$.eventId')),'NULL')<>'STRING'
 OR COALESCE(JSON_TYPE(JSON_EXTRACT(e.payload_json,'$.reportId')),'NULL')<>'STRING'
 OR NOT (BINARY JSON_UNQUOTE(JSON_EXTRACT(e.payload_json,'$.eventId'))<=>BINARY e.event_id)
 OR NOT (BINARY JSON_UNQUOTE(JSON_EXTRACT(e.payload_json,'$.reportId'))<=>BINARY e.report_id)
 OR COALESCE(JSON_TYPE(JSON_EXTRACT(e.payload_json,'$.actorUserId')),'NULL')<>'INTEGER'
 OR COALESCE(JSON_TYPE(JSON_EXTRACT(e.payload_json,'$.version')),'NULL')<>'INTEGER'
 OR COALESCE(JSON_TYPE(JSON_EXTRACT(e.payload_json,'$.schemaVersion')),'NULL')<>'INTEGER'
 OR COALESCE(JSON_TYPE(JSON_EXTRACT(e.payload_json,'$.status')),'NULL')<>'STRING';
INSERT INTO compact_report_guard SELECT IF(COUNT(*)=0,1,0) FROM `__SOURCE_SCHEMA__`.detection_report_outbox e
 JOIN quality_report q ON BINARY q.report_id=BINARY e.report_id
 WHERE CAST(JSON_UNQUOTE(JSON_EXTRACT(e.payload_json,'$.actorUserId')) AS DECIMAL(20,0)) NOT BETWEEN 1 AND 9223372036854775807
 OR CAST(JSON_UNQUOTE(JSON_EXTRACT(e.payload_json,'$.version')) AS DECIMAL(20,0)) NOT BETWEEN 2 AND 2147483647
 OR CAST(JSON_UNQUOTE(JSON_EXTRACT(e.payload_json,'$.version')) AS DECIMAL(20,0))>q.version
 OR NOT(JSON_EXTRACT(e.payload_json,'$.schemaVersion')<=>CAST('1' AS JSON))
 OR BINARY JSON_UNQUOTE(JSON_EXTRACT(e.payload_json,'$.status')) NOT IN (BINARY 'SUBMITTED',BINARY 'WITHDRAWN',BINARY 'APPROVED',BINARY 'REJECTED')
 OR NOT(BINARY e.event_type<=>BINARY CONCAT('detection.report.',LOWER(JSON_UNQUOTE(JSON_EXTRACT(e.payload_json,'$.status'))),'.v1'));
INSERT INTO compact_report_guard SELECT IF(COUNT(*)=0,1,0) FROM `__SOURCE_SCHEMA__`.detection_report_event_receipt r
 LEFT JOIN `__SOURCE_SCHEMA__`.detection_report_outbox e ON BINARY e.event_id=BINARY r.event_id
 WHERE e.event_id IS NULL OR NOT(BINARY r.report_id<=>BINARY e.report_id) OR NOT(BINARY r.event_type<=>BINARY e.event_type)
 OR NOT(r.report_version<=>JSON_EXTRACT(e.payload_json,'$.version')) OR NOT COALESCE(REGEXP_LIKE(r.payload_sha256,'^[a-f0-9]{64}$','c'),FALSE)
 OR CONVERT_TZ(r.consumed_at,@compact_validation_wall_offset,'+00:00') IS NULL;
INSERT INTO compact_report_guard SELECT IF(COUNT(*)=0,1,0) FROM `__SOURCE_SCHEMA__`.detection_report_event_receipt r
 JOIN `__SOURCE_SCHEMA__`.detection_report_outbox e ON BINARY e.event_id=BINARY r.event_id
 WHERE BINARY r.payload_sha256<>BINARY SHA2(CONCAT('{"eventId":',JSON_QUOTE(e.event_id),',"reportId":',JSON_QUOTE(e.report_id),
 ',"actorUserId":',JSON_UNQUOTE(JSON_EXTRACT(e.payload_json,'$.actorUserId')),',"status":',JSON_EXTRACT(e.payload_json,'$.status'),
 ',"version":',JSON_UNQUOTE(JSON_EXTRACT(e.payload_json,'$.version')),',"schemaVersion":1}'),256);
INSERT INTO compact_report_guard SELECT IF(COUNT(*)=0,1,0) FROM `__SOURCE_SCHEMA__`.detection_report_audit a
 LEFT JOIN quality_report q ON BINARY q.report_id=BINARY a.report_id
 WHERE q.id IS NULL OR COALESCE(a.actor_user_id,0)<=0 OR COALESCE(a.report_version,0)<1 OR a.report_version>q.version
 OR (a.snapshot_sha256 IS NOT NULL AND NOT REGEXP_LIKE(a.snapshot_sha256,'^[a-f0-9]{64}$','c'))
 OR CONVERT_TZ(a.created_at,@compact_validation_wall_offset,'+00:00') IS NULL;
INSERT INTO compact_report_guard SELECT IF(COUNT(*)=0,1,0) FROM `__SOURCE_SCHEMA__`.detection_report_event_state s
 LEFT JOIN `__SOURCE_SCHEMA__`.detection_report_event_receipt r ON BINARY r.event_id=BINARY s.last_event_id
 LEFT JOIN `__SOURCE_SCHEMA__`.detection_report_outbox e ON BINARY e.event_id=BINARY s.last_event_id
 WHERE r.event_id IS NULL OR e.event_id IS NULL OR NOT(BINARY r.report_id<=>BINARY s.report_id) OR NOT(r.report_version<=>s.last_version)
 OR NOT(BINARY s.status<=>BINARY JSON_UNQUOTE(JSON_EXTRACT(e.payload_json,'$.status')))
 OR NOT(s.last_version<=>(SELECT MAX(x.report_version) FROM `__SOURCE_SCHEMA__`.detection_report_event_receipt x WHERE BINARY x.report_id=BINARY s.report_id))
 OR CONVERT_TZ(s.updated_at,@compact_validation_wall_offset,'+00:00') IS NULL;
INSERT INTO compact_report_guard SELECT IF(COUNT(*)=0,1,0) FROM `__SOURCE_SCHEMA__`.detection_report_event_receipt r
 LEFT JOIN `__SOURCE_SCHEMA__`.detection_report_event_state s ON BINARY s.report_id=BINARY r.report_id WHERE s.report_id IS NULL;
INSERT INTO workflow_instance(workflow_id,kind,idempotency_scope,request_id,request_sha256,owner_user_id,actor_user_id,resource_type,resource_id,resource_revision,status,payload_version,payload_json,created_at,updated_at,finished_at,legacy_source,legacy_key,legacy_clock_json) SELECT SHA2(CONCAT('REPORT_COMMAND:',c.actor_user_id,':',c.request_id),256),'REPORT_COMMAND',CONCAT('OWNER:',c.actor_user_id),c.request_id,c.command_sha256,q.owner_user_id,c.actor_user_id,'QUALITY_REPORT',c.report_id,CAST(JSON_UNQUOTE(JSON_EXTRACT(c.response_json,'$.version')) AS UNSIGNED),'COMPLETED',1,JSON_OBJECT('responseJson',c.response_json),IF(@compact_source_clock_unresolved,NULL,CONVERT_TZ(c.created_at,@compact_validation_wall_offset,'+00:00')),IF(@compact_source_clock_unresolved,NULL,CONVERT_TZ(c.created_at,@compact_validation_wall_offset,'+00:00')),IF(@compact_source_clock_unresolved,NULL,CONVERT_TZ(c.created_at,@compact_validation_wall_offset,'+00:00')),'detection_report_command',CAST(JSON_ARRAY(c.actor_user_id,c.request_id) AS CHAR),IF(@compact_source_clock_unresolved,JSON_OBJECT('protocol','doorhandle-legacy-clock-v1','status','UNRESOLVED','sourceTable','detection_report_command','sourceKey',JSON_OBJECT('actor_user_id',c.`actor_user_id`,'request_id',c.`request_id`),'sourceSnapshotSha256','__SOURCE_SNAPSHOT_SHA256__','sourceRowSha256',SHA2(CAST(JSON_OBJECT('actor_user_id',c.`actor_user_id`,'request_id',c.`request_id`,'command_sha256',c.`command_sha256`,'report_id',c.`report_id`,'response_json',c.`response_json`,'created_at',CAST(c.`created_at` AS CHAR CHARACTER SET utf8mb4)) AS CHAR CHARACTER SET utf8mb4),256),'sourceWallTimes',JSON_OBJECT('created_at',CAST(c.`created_at` AS CHAR))),NULL) FROM `__SOURCE_SCHEMA__`.detection_report_command c JOIN quality_report q ON BINARY q.report_id=BINARY c.report_id;
INSERT INTO workflow_instance(workflow_id,kind,idempotency_scope,request_id,request_sha256,owner_user_id,actor_user_id,resource_type,resource_id,resource_revision,status,expires_at,payload_version,payload_json,created_at,updated_at,finished_at,legacy_source,legacy_key,legacy_clock_json) SELECT SHA2(CONCAT('REPORT_CONFIRMATION:',c.token),256),'REPORT_CONFIRMATION','REPORT_CONFIRMATION',c.token,SHA2(CONCAT(c.snapshot_sha256,':',c.decision_sha256),256),q.owner_user_id,c.actor_user_id,'QUALITY_REPORT',c.report_id,c.report_version,IF(c.used_at IS NULL,'PENDING','USED'),IF(@compact_source_clock_unresolved,NULL,CONVERT_TZ(c.expires_at,@compact_validation_wall_offset,'+00:00')),1,JSON_OBJECT('snapshotSha256',c.snapshot_sha256,'decisionSha256',c.decision_sha256),NULL,IF(@compact_source_clock_unresolved,NULL,CONVERT_TZ(c.used_at,@compact_validation_wall_offset,'+00:00')),IF(@compact_source_clock_unresolved,NULL,CONVERT_TZ(c.used_at,@compact_validation_wall_offset,'+00:00')),'detection_report_confirmation',c.token,IF(@compact_source_clock_unresolved,JSON_OBJECT('protocol','doorhandle-legacy-clock-v1','status','UNRESOLVED','sourceTable','detection_report_confirmation','sourceKey',JSON_OBJECT('token',c.`token`),'sourceSnapshotSha256','__SOURCE_SNAPSHOT_SHA256__','sourceRowSha256',SHA2(CAST(JSON_OBJECT('token',c.`token`,'report_id',c.`report_id`,'actor_user_id',c.`actor_user_id`,'report_version',c.`report_version`,'snapshot_sha256',c.`snapshot_sha256`,'decision_sha256',c.`decision_sha256`,'expires_at',CAST(c.`expires_at` AS CHAR CHARACTER SET utf8mb4),'used_at',CAST(c.`used_at` AS CHAR CHARACTER SET utf8mb4)) AS CHAR CHARACTER SET utf8mb4),256),'sourceWallTimes',JSON_OBJECT('expires_at',CAST(c.`expires_at` AS CHAR),'used_at',CAST(c.`used_at` AS CHAR))),NULL) FROM `__SOURCE_SCHEMA__`.detection_report_confirmation c JOIN quality_report q ON BINARY q.report_id=BINARY c.report_id;
INSERT INTO workflow_instance(workflow_id,kind,idempotency_scope,request_id,request_sha256,owner_user_id,actor_user_id,resource_type,resource_id,resource_revision,run_id,status,payload_version,payload_json,created_at,updated_at,finished_at,legacy_source,legacy_key,legacy_clock_json) SELECT SHA2(CONCAT('REPORT_AGENT_ORIGIN:',o.actor_user_id,':',o.request_id),256),'REPORT_AGENT_ORIGIN',CONCAT('OWNER:',o.actor_user_id),o.request_id,SHA2(CONCAT(o.actor_user_id,'|',o.report_id,'|',o.report_version,'|',CHAR_LENGTH(o.run_id),':',o.run_id,'|',o.tool_name),256),q.owner_user_id,o.actor_user_id,'QUALITY_REPORT',o.report_id,o.report_version,o.run_id,'COMPLETED',1,JSON_OBJECT('callId',o.call_id,'toolName',o.tool_name),IF(@compact_source_clock_unresolved,NULL,CONVERT_TZ(o.created_at,@compact_validation_wall_offset,'+00:00')),IF(@compact_source_clock_unresolved,NULL,CONVERT_TZ(o.created_at,@compact_validation_wall_offset,'+00:00')),IF(@compact_source_clock_unresolved,NULL,CONVERT_TZ(o.created_at,@compact_validation_wall_offset,'+00:00')),'detection_report_agent_origin',CAST(JSON_ARRAY(o.actor_user_id,o.request_id) AS CHAR),IF(@compact_source_clock_unresolved,JSON_OBJECT('protocol','doorhandle-legacy-clock-v1','status','UNRESOLVED','sourceTable','detection_report_agent_origin','sourceKey',JSON_OBJECT('actor_user_id',o.`actor_user_id`,'request_id',o.`request_id`),'sourceSnapshotSha256','__SOURCE_SNAPSHOT_SHA256__','sourceRowSha256',SHA2(CAST(JSON_OBJECT('actor_user_id',o.`actor_user_id`,'request_id',o.`request_id`,'report_id',o.`report_id`,'report_version',o.`report_version`,'run_id',o.`run_id`,'call_id',o.`call_id`,'tool_name',o.`tool_name`,'created_at',CAST(o.`created_at` AS CHAR CHARACTER SET utf8mb4)) AS CHAR CHARACTER SET utf8mb4),256),'sourceWallTimes',JSON_OBJECT('created_at',CAST(o.`created_at` AS CHAR))),NULL) FROM `__SOURCE_SCHEMA__`.detection_report_agent_origin o JOIN quality_report q ON BINARY q.report_id=BINARY o.report_id;
INSERT INTO workflow_instance(workflow_id,kind,idempotency_scope,request_id,request_sha256,owner_user_id,actor_user_id,resource_type,resource_id,resource_revision,status,fence,claim_token,lease_expires_at,attempts,next_attempt_at,error_code,payload_version,payload_json,created_at,updated_at,finished_at,legacy_source,legacy_key,legacy_clock_json) SELECT SHA2(CONCAT('REPORT_DELIVERY:',e.event_id),256),'REPORT_DELIVERY','REPORT_DELIVERY',e.event_id,SHA2(CONVERT(e.payload_json USING utf8mb4),256),q.owner_user_id,CAST(JSON_UNQUOTE(JSON_EXTRACT(e.payload_json,'$.actorUserId')) AS UNSIGNED),'QUALITY_REPORT',e.report_id,CAST(JSON_UNQUOTE(JSON_EXTRACT(e.payload_json,'$.version')) AS UNSIGNED),e.delivery_status,IF(e.delivery_status='PROCESSING',1,0),e.lease_token,IF(@compact_source_clock_unresolved,NULL,CONVERT_TZ(e.lease_expires_at,@compact_validation_wall_offset,'+00:00')),e.attempts,IF(@compact_source_clock_unresolved,NULL,CONVERT_TZ(e.next_attempt_at,@compact_validation_wall_offset,'+00:00')),e.last_error_code,1,JSON_OBJECT('eventType',e.event_type,'eventJson',e.payload_json),IF(@compact_source_clock_unresolved,NULL,CONVERT_TZ(e.created_at,@compact_validation_wall_offset,'+00:00')),IF(@compact_source_clock_unresolved,NULL,COALESCE(CONVERT_TZ(e.delivered_at,@compact_validation_wall_offset,'+00:00'),CONVERT_TZ(e.created_at,@compact_validation_wall_offset,'+00:00'))),IF(@compact_source_clock_unresolved,NULL,CONVERT_TZ(e.delivered_at,@compact_validation_wall_offset,'+00:00')),'detection_report_outbox',e.event_id,IF(@compact_source_clock_unresolved,JSON_OBJECT('protocol','doorhandle-legacy-clock-v1','status','UNRESOLVED','sourceTable','detection_report_outbox','sourceKey',JSON_OBJECT('event_id',e.`event_id`),'sourceSnapshotSha256','__SOURCE_SNAPSHOT_SHA256__','sourceRowSha256',SHA2(CAST(JSON_OBJECT('event_id',e.`event_id`,'report_id',e.`report_id`,'event_type',e.`event_type`,'payload_json',e.`payload_json`,'delivery_status',e.`delivery_status`,'created_at',CAST(e.`created_at` AS CHAR CHARACTER SET utf8mb4),'attempts',e.`attempts`,'next_attempt_at',CAST(e.`next_attempt_at` AS CHAR CHARACTER SET utf8mb4),'lease_token',e.`lease_token`,'lease_expires_at',CAST(e.`lease_expires_at` AS CHAR CHARACTER SET utf8mb4),'delivered_at',CAST(e.`delivered_at` AS CHAR CHARACTER SET utf8mb4),'last_error_code',e.`last_error_code`) AS CHAR CHARACTER SET utf8mb4),256),'sourceWallTimes',JSON_OBJECT('created_at',CAST(e.`created_at` AS CHAR),'next_attempt_at',CAST(e.`next_attempt_at` AS CHAR),'lease_expires_at',CAST(e.`lease_expires_at` AS CHAR),'delivered_at',CAST(e.`delivered_at` AS CHAR))),NULL) FROM `__SOURCE_SCHEMA__`.detection_report_outbox e JOIN quality_report q ON BINARY q.report_id=BINARY e.report_id;
INSERT INTO workflow_instance(workflow_id,kind,idempotency_scope,request_id,request_sha256,owner_user_id,actor_user_id,resource_type,resource_id,resource_revision,status,payload_version,payload_json,created_at,updated_at,finished_at,legacy_source,legacy_key,legacy_clock_json) SELECT SHA2(CONCAT('REPORT_CONSUMPTION:',r.event_id),256),'REPORT_CONSUMPTION','REPORT_CONSUMPTION',r.event_id,r.payload_sha256,q.owner_user_id,CAST(JSON_UNQUOTE(JSON_EXTRACT(e.payload_json,'$.actorUserId')) AS UNSIGNED),'QUALITY_REPORT',r.report_id,r.report_version,'COMPLETED',1,JSON_OBJECT('eventType',r.event_type,'payloadSha256',r.payload_sha256),IF(@compact_source_clock_unresolved,NULL,CONVERT_TZ(r.consumed_at,@compact_validation_wall_offset,'+00:00')),IF(@compact_source_clock_unresolved,NULL,CONVERT_TZ(r.consumed_at,@compact_validation_wall_offset,'+00:00')),IF(@compact_source_clock_unresolved,NULL,CONVERT_TZ(r.consumed_at,@compact_validation_wall_offset,'+00:00')),'detection_report_event_receipt',r.event_id,IF(@compact_source_clock_unresolved,JSON_OBJECT('protocol','doorhandle-legacy-clock-v1','status','UNRESOLVED','sourceTable','detection_report_event_receipt','sourceKey',JSON_OBJECT('event_id',r.`event_id`),'sourceSnapshotSha256','__SOURCE_SNAPSHOT_SHA256__','sourceRowSha256',SHA2(CAST(JSON_OBJECT('event_id',r.`event_id`,'report_id',r.`report_id`,'event_type',r.`event_type`,'report_version',r.`report_version`,'payload_sha256',r.`payload_sha256`,'consumed_at',CAST(r.`consumed_at` AS CHAR CHARACTER SET utf8mb4)) AS CHAR CHARACTER SET utf8mb4),256),'sourceWallTimes',JSON_OBJECT('consumed_at',CAST(r.`consumed_at` AS CHAR))),NULL) FROM `__SOURCE_SCHEMA__`.detection_report_event_receipt r JOIN quality_report q ON BINARY q.report_id=BINARY r.report_id JOIN `__SOURCE_SCHEMA__`.detection_report_outbox e ON BINARY e.event_id=BINARY r.event_id;
INSERT INTO audit_event(event_id,kind,owner_user_id,actor_user_id,resource_type,resource_id,action,revision,content_sha256,occurred_at,payload_version,payload_json,legacy_source,legacy_key,legacy_clock_json) SELECT CONCAT('legacy-report-audit-',a.id),'QUALITY_REPORT',q.owner_user_id,a.actor_user_id,'QUALITY_REPORT',a.report_id,a.action,a.report_version,a.snapshot_sha256,IF(@compact_source_clock_unresolved,NULL,CONVERT_TZ(a.created_at,@compact_validation_wall_offset,'+00:00')),1,JSON_OBJECT('actorUsername',a.actor_username,'beforeStatus',a.before_status,'afterStatus',a.after_status,'reason',a.reason),'detection_report_audit',CAST(a.id AS CHAR),IF(@compact_source_clock_unresolved,JSON_OBJECT('protocol','doorhandle-legacy-clock-v1','status','UNRESOLVED','sourceTable','detection_report_audit','sourceKey',JSON_OBJECT('id',a.`id`),'sourceSnapshotSha256','__SOURCE_SNAPSHOT_SHA256__','sourceRowSha256',SHA2(CAST(JSON_OBJECT('id',a.`id`,'report_id',a.`report_id`,'actor_user_id',a.`actor_user_id`,'actor_username',a.`actor_username`,'action',a.`action`,'before_status',a.`before_status`,'after_status',a.`after_status`,'report_version',a.`report_version`,'reason',a.`reason`,'snapshot_sha256',a.`snapshot_sha256`,'created_at',CAST(a.`created_at` AS CHAR CHARACTER SET utf8mb4)) AS CHAR CHARACTER SET utf8mb4),256),'sourceWallTimes',JSON_OBJECT('created_at',CAST(a.`created_at` AS CHAR))),NULL) FROM `__SOURCE_SCHEMA__`.detection_report_audit a JOIN quality_report q ON BINARY q.report_id=BINARY a.report_id ORDER BY a.id;
INSERT INTO runtime_state(namespace,owner_id,scope_key,revision,state_code,current_ref,counter_value,payload_version,payload_json,created_at,updated_at,legacy_clock_json) SELECT 'REPORT_EVENT_STATE',0,s.report_id,1,s.status,s.last_event_id,s.last_version,1,JSON_OBJECT('reportId',s.report_id,'lastEventId',s.last_event_id,'lastVersion',s.last_version,'status',s.status),NULL,IF(@compact_source_clock_unresolved,NULL,CONVERT_TZ(s.updated_at,@compact_validation_wall_offset,'+00:00')),IF(@compact_source_clock_unresolved,JSON_OBJECT('protocol','doorhandle-legacy-clock-v1','status','UNRESOLVED','sourceTable','detection_report_event_state','sourceKey',JSON_OBJECT('report_id',s.`report_id`),'sourceSnapshotSha256','__SOURCE_SNAPSHOT_SHA256__','sourceRowSha256',SHA2(CAST(JSON_OBJECT('report_id',s.`report_id`,'last_version',s.`last_version`,'status',s.`status`,'last_event_id',s.`last_event_id`,'updated_at',CAST(s.`updated_at` AS CHAR CHARACTER SET utf8mb4)) AS CHAR CHARACTER SET utf8mb4),256),'sourceWallTimes',JSON_OBJECT('updated_at',CAST(s.`updated_at` AS CHAR))),NULL) FROM `__SOURCE_SCHEMA__`.detection_report_event_state s;
INSERT INTO compact_report_guard SELECT IF(
 (SELECT COUNT(*) FROM workflow_instance WHERE kind='REPORT_COMMAND')=(SELECT COUNT(*) FROM `__SOURCE_SCHEMA__`.detection_report_command)
 AND (SELECT COUNT(*) FROM workflow_instance WHERE kind='REPORT_CONFIRMATION')=(SELECT COUNT(*) FROM `__SOURCE_SCHEMA__`.detection_report_confirmation)
 AND (SELECT COUNT(*) FROM workflow_instance WHERE kind='REPORT_AGENT_ORIGIN')=(SELECT COUNT(*) FROM `__SOURCE_SCHEMA__`.detection_report_agent_origin)
 AND (SELECT COUNT(*) FROM workflow_instance WHERE kind='REPORT_DELIVERY')=(SELECT COUNT(*) FROM `__SOURCE_SCHEMA__`.detection_report_outbox)
 AND (SELECT COUNT(*) FROM workflow_instance WHERE kind='REPORT_CONSUMPTION')=(SELECT COUNT(*) FROM `__SOURCE_SCHEMA__`.detection_report_event_receipt)
 AND (SELECT COUNT(*) FROM audit_event WHERE kind='QUALITY_REPORT')=(SELECT COUNT(*) FROM `__SOURCE_SCHEMA__`.detection_report_audit)
 AND (SELECT COUNT(*) FROM runtime_state WHERE namespace='REPORT_EVENT_STATE')=(SELECT COUNT(*) FROM `__SOURCE_SCHEMA__`.detection_report_event_state),1,0);
INSERT INTO compact_report_guard SELECT IF(COUNT(*)=0,1,0) FROM `__SOURCE_SCHEMA__`.detection_report_command c JOIN quality_report q ON BINARY q.report_id=BINARY c.report_id
 LEFT JOIN workflow_instance t ON BINARY t.workflow_id=BINARY (SHA2(CONCAT('REPORT_COMMAND:',c.actor_user_id,':',c.request_id),256))
 WHERE t.workflow_id IS NULL
 OR NOT(BINARY t.workflow_id<=>BINARY (SHA2(CONCAT('REPORT_COMMAND:',c.actor_user_id,':',c.request_id),256)))
 OR NOT(BINARY t.kind<=>BINARY ('REPORT_COMMAND'))
 OR NOT(BINARY t.idempotency_scope<=>BINARY (CONCAT('OWNER:',c.actor_user_id)))
 OR NOT(BINARY t.request_id<=>BINARY (c.request_id))
 OR NOT(BINARY t.request_sha256<=>BINARY (c.command_sha256))
 OR NOT(t.owner_user_id<=>(q.owner_user_id))
 OR NOT(t.actor_user_id<=>(c.actor_user_id))
 OR NOT(t.parent_workflow_id<=>(NULL))
 OR NOT(BINARY t.resource_type<=>BINARY ('QUALITY_REPORT'))
 OR NOT(BINARY t.resource_id<=>BINARY (c.report_id))
 OR NOT(t.resource_revision<=>(CAST(JSON_UNQUOTE(JSON_EXTRACT(c.response_json,'$.version')) AS UNSIGNED)))
 OR NOT(t.requested_tokens<=>(NULL))
 OR NOT(t.decider_user_id<=>(NULL))
 OR NOT(BINARY t.session_id<=>BINARY (NULL))
 OR NOT(BINARY t.run_id<=>BINARY (NULL))
 OR NOT(BINARY t.chat_action_session_id<=>BINARY (NULL))
 OR NOT(t.confirmation_recorded_at<=>(NULL))
 OR NOT(BINARY t.status<=>BINARY ('COMPLETED'))
 OR NOT(t.revision<=>(0))
 OR NOT(t.fence<=>(0))
 OR NOT(t.active_slot<=>(NULL))
 OR NOT(BINARY t.claim_token<=>BINARY (NULL))
 OR NOT(t.lease_expires_at<=>(NULL))
 OR NOT(t.attempts<=>(0))
 OR NOT(t.effective_date<=>(NULL))
 OR NOT(t.scheduled_for<=>(NULL))
 OR NOT(BINARY t.error_code<=>BINARY (NULL))
 OR NOT(t.next_attempt_at<=>(NULL))
 OR NOT(t.expires_at<=>(NULL))
 OR NOT(BINARY t.execution_state<=>BINARY (NULL))
 OR NOT(t.reserved_bytes<=>(NULL))
 OR NOT(t.exit_verified<=>(NULL))
 OR NOT(t.execution_deadline<=>(NULL))
 OR NOT(t.payload_version<=>(1))
 OR NOT(BINARY t.payload_json<=>BINARY (JSON_OBJECT('responseJson',c.response_json)))
 OR NOT(t.result_version<=>(NULL))
 OR NOT(BINARY t.result_json<=>BINARY (NULL))
 OR NOT(BINARY t.result_sha256<=>BINARY (NULL))
 OR NOT((t.created_at<=>IF(@compact_source_clock_unresolved,NULL,(CONVERT_TZ(c.created_at,@compact_validation_wall_offset,'+00:00')))))
 OR NOT((t.updated_at<=>IF(@compact_source_clock_unresolved,NULL,(CONVERT_TZ(c.created_at,@compact_validation_wall_offset,'+00:00')))))
 OR NOT((t.finished_at<=>IF(@compact_source_clock_unresolved,NULL,(CONVERT_TZ(c.created_at,@compact_validation_wall_offset,'+00:00')))))
 OR NOT(BINARY t.legacy_source<=>BINARY ('detection_report_command'))
 OR NOT(BINARY t.legacy_key<=>BINARY (CAST(JSON_ARRAY(c.actor_user_id,c.request_id) AS CHAR)))
 OR NOT(BINARY t.call_id<=>BINARY (NULL))
 OR NOT(BINARY t.mcp_installation_id<=>BINARY (NULL))
 OR NOT(BINARY t.mcp_prior_installation_id<=>BINARY (NULL))
 OR NOT(BINARY t.mcp_owner_username<=>BINARY (NULL))
 OR NOT(BINARY t.mcp_runtime_sha256<=>BINARY (NULL))
 OR NOT(BINARY t.mcp_pool_id<=>BINARY (NULL))
 OR NOT(BINARY t.mcp_purpose<=>BINARY (NULL))
 OR NOT(BINARY t.mcp_transport<=>BINARY (NULL))
 OR NOT(BINARY t.mcp_image_id<=>BINARY (NULL))
 OR NOT(t.mcp_exit_verified<=>(NULL))
 OR NOT(t.mcp_cleanup_confirmed<=>(NULL))
 OR NOT(BINARY t.mcp_worker_token<=>BINARY (NULL))
 OR NOT(t.mcp_writer_exit_verified<=>(NULL))
 OR NOT(t.mcp_retained_for_rollback<=>(NULL))
 OR NOT(BINARY t.mcp_package_version<=>BINARY (NULL))
 OR NOT(BINARY t.mcp_manifest_json<=>BINARY (NULL))
 OR NOT(BINARY t.mcp_manifest_sha256<=>BINARY (NULL))
 OR NOT(BINARY t.mcp_cleanup_request<=>BINARY (NULL))
 OR NOT(t.mcp_cleanup_expires_at<=>(NULL))
 OR NOT(BINARY t.mcp_reconcile_request<=>BINARY (NULL))
 OR NOT(t.mcp_reconcile_expires_at<=>(NULL))
 OR NOT(BINARY t.mcp_writer_evidence_code<=>BINARY (NULL))
 OR NOT(BINARY t.mcp_node_sha256<=>BINARY (NULL))
 OR NOT(t.mcp_controller_pid<=>(NULL))
 OR NOT(BINARY t.mcp_controller_started<=>BINARY (NULL))
 OR NOT(BINARY t.mcp_container_id<=>BINARY (NULL))
 OR NOT(BINARY t.mcp_container_started<=>BINARY (NULL))
 OR NOT(BINARY t.mcp_controller_pool_id<=>BINARY (NULL))
 OR NOT(BINARY t.mcp_native_pool_id<=>BINARY (NULL))
 OR NOT(BINARY t.mcp_action<=>BINARY (NULL))
 OR NOT(t.mcp_retention_protocol<=>(NULL))
 OR NOT(t.mcp_source_created_at<=>(NULL))
 OR NOT(t.mcp_source_updated_at<=>(NULL))
 OR NOT(BINARY t.mcp_source_utc_offset<=>BINARY (NULL))
 OR NOT(BINARY t.digest_legacy_row_json<=>BINARY (NULL));
INSERT INTO compact_report_guard SELECT IF(COUNT(*)=0,1,0) FROM `__SOURCE_SCHEMA__`.detection_report_confirmation c JOIN quality_report q ON BINARY q.report_id=BINARY c.report_id
 LEFT JOIN workflow_instance t ON BINARY t.workflow_id=BINARY (SHA2(CONCAT('REPORT_CONFIRMATION:',c.token),256))
 WHERE t.workflow_id IS NULL
 OR NOT(BINARY t.workflow_id<=>BINARY (SHA2(CONCAT('REPORT_CONFIRMATION:',c.token),256)))
 OR NOT(BINARY t.kind<=>BINARY ('REPORT_CONFIRMATION'))
 OR NOT(BINARY t.idempotency_scope<=>BINARY ('REPORT_CONFIRMATION'))
 OR NOT(BINARY t.request_id<=>BINARY (c.token))
 OR NOT(BINARY t.request_sha256<=>BINARY (SHA2(CONCAT(c.snapshot_sha256,':',c.decision_sha256),256)))
 OR NOT(t.owner_user_id<=>(q.owner_user_id))
 OR NOT(t.actor_user_id<=>(c.actor_user_id))
 OR NOT(t.parent_workflow_id<=>(NULL))
 OR NOT(BINARY t.resource_type<=>BINARY ('QUALITY_REPORT'))
 OR NOT(BINARY t.resource_id<=>BINARY (c.report_id))
 OR NOT(t.resource_revision<=>(c.report_version))
 OR NOT(t.requested_tokens<=>(NULL))
 OR NOT(t.decider_user_id<=>(NULL))
 OR NOT(BINARY t.session_id<=>BINARY (NULL))
 OR NOT(BINARY t.run_id<=>BINARY (NULL))
 OR NOT(BINARY t.chat_action_session_id<=>BINARY (NULL))
 OR NOT(t.confirmation_recorded_at<=>(NULL))
 OR NOT(BINARY t.status<=>BINARY (IF(c.used_at IS NULL,'PENDING','USED')))
 OR NOT(t.revision<=>(0))
 OR NOT(t.fence<=>(0))
 OR NOT(t.active_slot<=>(NULL))
 OR NOT(BINARY t.claim_token<=>BINARY (NULL))
 OR NOT(t.lease_expires_at<=>(NULL))
 OR NOT(t.attempts<=>(0))
 OR NOT(t.effective_date<=>(NULL))
 OR NOT(t.scheduled_for<=>(NULL))
 OR NOT(BINARY t.error_code<=>BINARY (NULL))
 OR NOT(t.next_attempt_at<=>(NULL))
 OR NOT((t.expires_at<=>IF(@compact_source_clock_unresolved,NULL,(CONVERT_TZ(c.expires_at,@compact_validation_wall_offset,'+00:00')))))
 OR NOT(BINARY t.execution_state<=>BINARY (NULL))
 OR NOT(t.reserved_bytes<=>(NULL))
 OR NOT(t.exit_verified<=>(NULL))
 OR NOT(t.execution_deadline<=>(NULL))
 OR NOT(t.payload_version<=>(1))
 OR NOT(BINARY t.payload_json<=>BINARY (JSON_OBJECT('snapshotSha256',c.snapshot_sha256,'decisionSha256',c.decision_sha256)))
 OR NOT(t.result_version<=>(NULL))
 OR NOT(BINARY t.result_json<=>BINARY (NULL))
 OR NOT(BINARY t.result_sha256<=>BINARY (NULL))
 OR NOT(t.created_at<=>(NULL))
 OR NOT((t.updated_at<=>IF(@compact_source_clock_unresolved,NULL,(CONVERT_TZ(c.used_at,@compact_validation_wall_offset,'+00:00')))))
 OR NOT((t.finished_at<=>IF(@compact_source_clock_unresolved,NULL,(CONVERT_TZ(c.used_at,@compact_validation_wall_offset,'+00:00')))))
 OR NOT(BINARY t.legacy_source<=>BINARY ('detection_report_confirmation'))
 OR NOT(BINARY t.legacy_key<=>BINARY (c.token))
 OR NOT(BINARY t.call_id<=>BINARY (NULL))
 OR NOT(BINARY t.mcp_installation_id<=>BINARY (NULL))
 OR NOT(BINARY t.mcp_prior_installation_id<=>BINARY (NULL))
 OR NOT(BINARY t.mcp_owner_username<=>BINARY (NULL))
 OR NOT(BINARY t.mcp_runtime_sha256<=>BINARY (NULL))
 OR NOT(BINARY t.mcp_pool_id<=>BINARY (NULL))
 OR NOT(BINARY t.mcp_purpose<=>BINARY (NULL))
 OR NOT(BINARY t.mcp_transport<=>BINARY (NULL))
 OR NOT(BINARY t.mcp_image_id<=>BINARY (NULL))
 OR NOT(t.mcp_exit_verified<=>(NULL))
 OR NOT(t.mcp_cleanup_confirmed<=>(NULL))
 OR NOT(BINARY t.mcp_worker_token<=>BINARY (NULL))
 OR NOT(t.mcp_writer_exit_verified<=>(NULL))
 OR NOT(t.mcp_retained_for_rollback<=>(NULL))
 OR NOT(BINARY t.mcp_package_version<=>BINARY (NULL))
 OR NOT(BINARY t.mcp_manifest_json<=>BINARY (NULL))
 OR NOT(BINARY t.mcp_manifest_sha256<=>BINARY (NULL))
 OR NOT(BINARY t.mcp_cleanup_request<=>BINARY (NULL))
 OR NOT(t.mcp_cleanup_expires_at<=>(NULL))
 OR NOT(BINARY t.mcp_reconcile_request<=>BINARY (NULL))
 OR NOT(t.mcp_reconcile_expires_at<=>(NULL))
 OR NOT(BINARY t.mcp_writer_evidence_code<=>BINARY (NULL))
 OR NOT(BINARY t.mcp_node_sha256<=>BINARY (NULL))
 OR NOT(t.mcp_controller_pid<=>(NULL))
 OR NOT(BINARY t.mcp_controller_started<=>BINARY (NULL))
 OR NOT(BINARY t.mcp_container_id<=>BINARY (NULL))
 OR NOT(BINARY t.mcp_container_started<=>BINARY (NULL))
 OR NOT(BINARY t.mcp_controller_pool_id<=>BINARY (NULL))
 OR NOT(BINARY t.mcp_native_pool_id<=>BINARY (NULL))
 OR NOT(BINARY t.mcp_action<=>BINARY (NULL))
 OR NOT(t.mcp_retention_protocol<=>(NULL))
 OR NOT(t.mcp_source_created_at<=>(NULL))
 OR NOT(t.mcp_source_updated_at<=>(NULL))
 OR NOT(BINARY t.mcp_source_utc_offset<=>BINARY (NULL))
 OR NOT(BINARY t.digest_legacy_row_json<=>BINARY (NULL));
INSERT INTO compact_report_guard SELECT IF(COUNT(*)=0,1,0) FROM `__SOURCE_SCHEMA__`.detection_report_agent_origin o JOIN quality_report q ON BINARY q.report_id=BINARY o.report_id
 LEFT JOIN workflow_instance t ON BINARY t.workflow_id=BINARY (SHA2(CONCAT('REPORT_AGENT_ORIGIN:',o.actor_user_id,':',o.request_id),256))
 WHERE t.workflow_id IS NULL
 OR NOT(BINARY t.workflow_id<=>BINARY (SHA2(CONCAT('REPORT_AGENT_ORIGIN:',o.actor_user_id,':',o.request_id),256)))
 OR NOT(BINARY t.kind<=>BINARY ('REPORT_AGENT_ORIGIN'))
 OR NOT(BINARY t.idempotency_scope<=>BINARY (CONCAT('OWNER:',o.actor_user_id)))
 OR NOT(BINARY t.request_id<=>BINARY (o.request_id))
 OR NOT(BINARY t.request_sha256<=>BINARY (SHA2(CONCAT(o.actor_user_id,'|',o.report_id,'|',o.report_version,'|',CHAR_LENGTH(o.run_id),':',o.run_id,'|',o.tool_name),256)))
 OR NOT(t.owner_user_id<=>(q.owner_user_id))
 OR NOT(t.actor_user_id<=>(o.actor_user_id))
 OR NOT(t.parent_workflow_id<=>(NULL))
 OR NOT(BINARY t.resource_type<=>BINARY ('QUALITY_REPORT'))
 OR NOT(BINARY t.resource_id<=>BINARY (o.report_id))
 OR NOT(t.resource_revision<=>(o.report_version))
 OR NOT(t.requested_tokens<=>(NULL))
 OR NOT(t.decider_user_id<=>(NULL))
 OR NOT(BINARY t.session_id<=>BINARY (NULL))
 OR NOT(BINARY t.run_id<=>BINARY (o.run_id))
 OR NOT(BINARY t.chat_action_session_id<=>BINARY (NULL))
 OR NOT(t.confirmation_recorded_at<=>(NULL))
 OR NOT(BINARY t.status<=>BINARY ('COMPLETED'))
 OR NOT(t.revision<=>(0))
 OR NOT(t.fence<=>(0))
 OR NOT(t.active_slot<=>(NULL))
 OR NOT(BINARY t.claim_token<=>BINARY (NULL))
 OR NOT(t.lease_expires_at<=>(NULL))
 OR NOT(t.attempts<=>(0))
 OR NOT(t.effective_date<=>(NULL))
 OR NOT(t.scheduled_for<=>(NULL))
 OR NOT(BINARY t.error_code<=>BINARY (NULL))
 OR NOT(t.next_attempt_at<=>(NULL))
 OR NOT(t.expires_at<=>(NULL))
 OR NOT(BINARY t.execution_state<=>BINARY (NULL))
 OR NOT(t.reserved_bytes<=>(NULL))
 OR NOT(t.exit_verified<=>(NULL))
 OR NOT(t.execution_deadline<=>(NULL))
 OR NOT(t.payload_version<=>(1))
 OR NOT(BINARY t.payload_json<=>BINARY (JSON_OBJECT('callId',o.call_id,'toolName',o.tool_name)))
 OR NOT(t.result_version<=>(NULL))
 OR NOT(BINARY t.result_json<=>BINARY (NULL))
 OR NOT(BINARY t.result_sha256<=>BINARY (NULL))
 OR NOT((t.created_at<=>IF(@compact_source_clock_unresolved,NULL,(CONVERT_TZ(o.created_at,@compact_validation_wall_offset,'+00:00')))))
 OR NOT((t.updated_at<=>IF(@compact_source_clock_unresolved,NULL,(CONVERT_TZ(o.created_at,@compact_validation_wall_offset,'+00:00')))))
 OR NOT((t.finished_at<=>IF(@compact_source_clock_unresolved,NULL,(CONVERT_TZ(o.created_at,@compact_validation_wall_offset,'+00:00')))))
 OR NOT(BINARY t.legacy_source<=>BINARY ('detection_report_agent_origin'))
 OR NOT(BINARY t.legacy_key<=>BINARY (CAST(JSON_ARRAY(o.actor_user_id,o.request_id) AS CHAR)))
 OR NOT(BINARY t.call_id<=>BINARY (NULL))
 OR NOT(BINARY t.mcp_installation_id<=>BINARY (NULL))
 OR NOT(BINARY t.mcp_prior_installation_id<=>BINARY (NULL))
 OR NOT(BINARY t.mcp_owner_username<=>BINARY (NULL))
 OR NOT(BINARY t.mcp_runtime_sha256<=>BINARY (NULL))
 OR NOT(BINARY t.mcp_pool_id<=>BINARY (NULL))
 OR NOT(BINARY t.mcp_purpose<=>BINARY (NULL))
 OR NOT(BINARY t.mcp_transport<=>BINARY (NULL))
 OR NOT(BINARY t.mcp_image_id<=>BINARY (NULL))
 OR NOT(t.mcp_exit_verified<=>(NULL))
 OR NOT(t.mcp_cleanup_confirmed<=>(NULL))
 OR NOT(BINARY t.mcp_worker_token<=>BINARY (NULL))
 OR NOT(t.mcp_writer_exit_verified<=>(NULL))
 OR NOT(t.mcp_retained_for_rollback<=>(NULL))
 OR NOT(BINARY t.mcp_package_version<=>BINARY (NULL))
 OR NOT(BINARY t.mcp_manifest_json<=>BINARY (NULL))
 OR NOT(BINARY t.mcp_manifest_sha256<=>BINARY (NULL))
 OR NOT(BINARY t.mcp_cleanup_request<=>BINARY (NULL))
 OR NOT(t.mcp_cleanup_expires_at<=>(NULL))
 OR NOT(BINARY t.mcp_reconcile_request<=>BINARY (NULL))
 OR NOT(t.mcp_reconcile_expires_at<=>(NULL))
 OR NOT(BINARY t.mcp_writer_evidence_code<=>BINARY (NULL))
 OR NOT(BINARY t.mcp_node_sha256<=>BINARY (NULL))
 OR NOT(t.mcp_controller_pid<=>(NULL))
 OR NOT(BINARY t.mcp_controller_started<=>BINARY (NULL))
 OR NOT(BINARY t.mcp_container_id<=>BINARY (NULL))
 OR NOT(BINARY t.mcp_container_started<=>BINARY (NULL))
 OR NOT(BINARY t.mcp_controller_pool_id<=>BINARY (NULL))
 OR NOT(BINARY t.mcp_native_pool_id<=>BINARY (NULL))
 OR NOT(BINARY t.mcp_action<=>BINARY (NULL))
 OR NOT(t.mcp_retention_protocol<=>(NULL))
 OR NOT(t.mcp_source_created_at<=>(NULL))
 OR NOT(t.mcp_source_updated_at<=>(NULL))
 OR NOT(BINARY t.mcp_source_utc_offset<=>BINARY (NULL))
 OR NOT(BINARY t.digest_legacy_row_json<=>BINARY (NULL));
INSERT INTO compact_report_guard SELECT IF(COUNT(*)=0,1,0) FROM `__SOURCE_SCHEMA__`.detection_report_outbox e JOIN quality_report q ON BINARY q.report_id=BINARY e.report_id
 LEFT JOIN workflow_instance t ON BINARY t.workflow_id=BINARY (SHA2(CONCAT('REPORT_DELIVERY:',e.event_id),256))
 WHERE t.workflow_id IS NULL
 OR NOT(BINARY t.workflow_id<=>BINARY (SHA2(CONCAT('REPORT_DELIVERY:',e.event_id),256)))
 OR NOT(BINARY t.kind<=>BINARY ('REPORT_DELIVERY'))
 OR NOT(BINARY t.idempotency_scope<=>BINARY ('REPORT_DELIVERY'))
 OR NOT(BINARY t.request_id<=>BINARY (e.event_id))
 OR NOT(BINARY t.request_sha256<=>BINARY (SHA2(CONVERT(e.payload_json USING utf8mb4),256)))
 OR NOT(t.owner_user_id<=>(q.owner_user_id))
 OR NOT(t.actor_user_id<=>(CAST(JSON_UNQUOTE(JSON_EXTRACT(e.payload_json,'$.actorUserId')) AS UNSIGNED)))
 OR NOT(t.parent_workflow_id<=>(NULL))
 OR NOT(BINARY t.resource_type<=>BINARY ('QUALITY_REPORT'))
 OR NOT(BINARY t.resource_id<=>BINARY (e.report_id))
 OR NOT(t.resource_revision<=>(CAST(JSON_UNQUOTE(JSON_EXTRACT(e.payload_json,'$.version')) AS UNSIGNED)))
 OR NOT(t.requested_tokens<=>(NULL))
 OR NOT(t.decider_user_id<=>(NULL))
 OR NOT(BINARY t.session_id<=>BINARY (NULL))
 OR NOT(BINARY t.run_id<=>BINARY (NULL))
 OR NOT(BINARY t.chat_action_session_id<=>BINARY (NULL))
 OR NOT(t.confirmation_recorded_at<=>(NULL))
 OR NOT(BINARY t.status<=>BINARY (e.delivery_status))
 OR NOT(t.revision<=>(0))
 OR NOT(t.fence<=>(IF(e.delivery_status='PROCESSING',1,0)))
 OR NOT(t.active_slot<=>(NULL))
 OR NOT(BINARY t.claim_token<=>BINARY (e.lease_token))
 OR NOT((t.lease_expires_at<=>IF(@compact_source_clock_unresolved,NULL,(CONVERT_TZ(e.lease_expires_at,@compact_validation_wall_offset,'+00:00')))))
 OR NOT(t.attempts<=>(e.attempts))
 OR NOT(t.effective_date<=>(NULL))
 OR NOT(t.scheduled_for<=>(NULL))
 OR NOT(BINARY t.error_code<=>BINARY (e.last_error_code))
 OR NOT((t.next_attempt_at<=>IF(@compact_source_clock_unresolved,NULL,(CONVERT_TZ(e.next_attempt_at,@compact_validation_wall_offset,'+00:00')))))
 OR NOT(t.expires_at<=>(NULL))
 OR NOT(BINARY t.execution_state<=>BINARY (NULL))
 OR NOT(t.reserved_bytes<=>(NULL))
 OR NOT(t.exit_verified<=>(NULL))
 OR NOT(t.execution_deadline<=>(NULL))
 OR NOT(t.payload_version<=>(1))
 OR NOT(BINARY t.payload_json<=>BINARY (JSON_OBJECT('eventType',e.event_type,'eventJson',e.payload_json)))
 OR NOT(t.result_version<=>(NULL))
 OR NOT(BINARY t.result_json<=>BINARY (NULL))
 OR NOT(BINARY t.result_sha256<=>BINARY (NULL))
 OR NOT((t.created_at<=>IF(@compact_source_clock_unresolved,NULL,(CONVERT_TZ(e.created_at,@compact_validation_wall_offset,'+00:00')))))
 OR NOT((t.updated_at<=>IF(@compact_source_clock_unresolved,NULL,(COALESCE(CONVERT_TZ(e.delivered_at,@compact_validation_wall_offset,'+00:00'),CONVERT_TZ(e.created_at,@compact_validation_wall_offset,'+00:00'))))))
 OR NOT((t.finished_at<=>IF(@compact_source_clock_unresolved,NULL,(CONVERT_TZ(e.delivered_at,@compact_validation_wall_offset,'+00:00')))))
 OR NOT(BINARY t.legacy_source<=>BINARY ('detection_report_outbox'))
 OR NOT(BINARY t.legacy_key<=>BINARY (e.event_id))
 OR NOT(BINARY t.call_id<=>BINARY (NULL))
 OR NOT(BINARY t.mcp_installation_id<=>BINARY (NULL))
 OR NOT(BINARY t.mcp_prior_installation_id<=>BINARY (NULL))
 OR NOT(BINARY t.mcp_owner_username<=>BINARY (NULL))
 OR NOT(BINARY t.mcp_runtime_sha256<=>BINARY (NULL))
 OR NOT(BINARY t.mcp_pool_id<=>BINARY (NULL))
 OR NOT(BINARY t.mcp_purpose<=>BINARY (NULL))
 OR NOT(BINARY t.mcp_transport<=>BINARY (NULL))
 OR NOT(BINARY t.mcp_image_id<=>BINARY (NULL))
 OR NOT(t.mcp_exit_verified<=>(NULL))
 OR NOT(t.mcp_cleanup_confirmed<=>(NULL))
 OR NOT(BINARY t.mcp_worker_token<=>BINARY (NULL))
 OR NOT(t.mcp_writer_exit_verified<=>(NULL))
 OR NOT(t.mcp_retained_for_rollback<=>(NULL))
 OR NOT(BINARY t.mcp_package_version<=>BINARY (NULL))
 OR NOT(BINARY t.mcp_manifest_json<=>BINARY (NULL))
 OR NOT(BINARY t.mcp_manifest_sha256<=>BINARY (NULL))
 OR NOT(BINARY t.mcp_cleanup_request<=>BINARY (NULL))
 OR NOT(t.mcp_cleanup_expires_at<=>(NULL))
 OR NOT(BINARY t.mcp_reconcile_request<=>BINARY (NULL))
 OR NOT(t.mcp_reconcile_expires_at<=>(NULL))
 OR NOT(BINARY t.mcp_writer_evidence_code<=>BINARY (NULL))
 OR NOT(BINARY t.mcp_node_sha256<=>BINARY (NULL))
 OR NOT(t.mcp_controller_pid<=>(NULL))
 OR NOT(BINARY t.mcp_controller_started<=>BINARY (NULL))
 OR NOT(BINARY t.mcp_container_id<=>BINARY (NULL))
 OR NOT(BINARY t.mcp_container_started<=>BINARY (NULL))
 OR NOT(BINARY t.mcp_controller_pool_id<=>BINARY (NULL))
 OR NOT(BINARY t.mcp_native_pool_id<=>BINARY (NULL))
 OR NOT(BINARY t.mcp_action<=>BINARY (NULL))
 OR NOT(t.mcp_retention_protocol<=>(NULL))
 OR NOT(t.mcp_source_created_at<=>(NULL))
 OR NOT(t.mcp_source_updated_at<=>(NULL))
 OR NOT(BINARY t.mcp_source_utc_offset<=>BINARY (NULL))
 OR NOT(BINARY t.digest_legacy_row_json<=>BINARY (NULL));
INSERT INTO compact_report_guard SELECT IF(COUNT(*)=0,1,0) FROM `__SOURCE_SCHEMA__`.detection_report_event_receipt r JOIN quality_report q ON BINARY q.report_id=BINARY r.report_id JOIN `__SOURCE_SCHEMA__`.detection_report_outbox e ON BINARY e.event_id=BINARY r.event_id
 LEFT JOIN workflow_instance t ON BINARY t.workflow_id=BINARY (SHA2(CONCAT('REPORT_CONSUMPTION:',r.event_id),256))
 WHERE t.workflow_id IS NULL
 OR NOT(BINARY t.workflow_id<=>BINARY (SHA2(CONCAT('REPORT_CONSUMPTION:',r.event_id),256)))
 OR NOT(BINARY t.kind<=>BINARY ('REPORT_CONSUMPTION'))
 OR NOT(BINARY t.idempotency_scope<=>BINARY ('REPORT_CONSUMPTION'))
 OR NOT(BINARY t.request_id<=>BINARY (r.event_id))
 OR NOT(BINARY t.request_sha256<=>BINARY (r.payload_sha256))
 OR NOT(t.owner_user_id<=>(q.owner_user_id))
 OR NOT(t.actor_user_id<=>(CAST(JSON_UNQUOTE(JSON_EXTRACT(e.payload_json,'$.actorUserId')) AS UNSIGNED)))
 OR NOT(t.parent_workflow_id<=>(NULL))
 OR NOT(BINARY t.resource_type<=>BINARY ('QUALITY_REPORT'))
 OR NOT(BINARY t.resource_id<=>BINARY (r.report_id))
 OR NOT(t.resource_revision<=>(r.report_version))
 OR NOT(t.requested_tokens<=>(NULL))
 OR NOT(t.decider_user_id<=>(NULL))
 OR NOT(BINARY t.session_id<=>BINARY (NULL))
 OR NOT(BINARY t.run_id<=>BINARY (NULL))
 OR NOT(BINARY t.chat_action_session_id<=>BINARY (NULL))
 OR NOT(t.confirmation_recorded_at<=>(NULL))
 OR NOT(BINARY t.status<=>BINARY ('COMPLETED'))
 OR NOT(t.revision<=>(0))
 OR NOT(t.fence<=>(0))
 OR NOT(t.active_slot<=>(NULL))
 OR NOT(BINARY t.claim_token<=>BINARY (NULL))
 OR NOT(t.lease_expires_at<=>(NULL))
 OR NOT(t.attempts<=>(0))
 OR NOT(t.effective_date<=>(NULL))
 OR NOT(t.scheduled_for<=>(NULL))
 OR NOT(BINARY t.error_code<=>BINARY (NULL))
 OR NOT(t.next_attempt_at<=>(NULL))
 OR NOT(t.expires_at<=>(NULL))
 OR NOT(BINARY t.execution_state<=>BINARY (NULL))
 OR NOT(t.reserved_bytes<=>(NULL))
 OR NOT(t.exit_verified<=>(NULL))
 OR NOT(t.execution_deadline<=>(NULL))
 OR NOT(t.payload_version<=>(1))
 OR NOT(BINARY t.payload_json<=>BINARY (JSON_OBJECT('eventType',r.event_type,'payloadSha256',r.payload_sha256)))
 OR NOT(t.result_version<=>(NULL))
 OR NOT(BINARY t.result_json<=>BINARY (NULL))
 OR NOT(BINARY t.result_sha256<=>BINARY (NULL))
 OR NOT((t.created_at<=>IF(@compact_source_clock_unresolved,NULL,(CONVERT_TZ(r.consumed_at,@compact_validation_wall_offset,'+00:00')))))
 OR NOT((t.updated_at<=>IF(@compact_source_clock_unresolved,NULL,(CONVERT_TZ(r.consumed_at,@compact_validation_wall_offset,'+00:00')))))
 OR NOT((t.finished_at<=>IF(@compact_source_clock_unresolved,NULL,(CONVERT_TZ(r.consumed_at,@compact_validation_wall_offset,'+00:00')))))
 OR NOT(BINARY t.legacy_source<=>BINARY ('detection_report_event_receipt'))
 OR NOT(BINARY t.legacy_key<=>BINARY (r.event_id))
 OR NOT(BINARY t.call_id<=>BINARY (NULL))
 OR NOT(BINARY t.mcp_installation_id<=>BINARY (NULL))
 OR NOT(BINARY t.mcp_prior_installation_id<=>BINARY (NULL))
 OR NOT(BINARY t.mcp_owner_username<=>BINARY (NULL))
 OR NOT(BINARY t.mcp_runtime_sha256<=>BINARY (NULL))
 OR NOT(BINARY t.mcp_pool_id<=>BINARY (NULL))
 OR NOT(BINARY t.mcp_purpose<=>BINARY (NULL))
 OR NOT(BINARY t.mcp_transport<=>BINARY (NULL))
 OR NOT(BINARY t.mcp_image_id<=>BINARY (NULL))
 OR NOT(t.mcp_exit_verified<=>(NULL))
 OR NOT(t.mcp_cleanup_confirmed<=>(NULL))
 OR NOT(BINARY t.mcp_worker_token<=>BINARY (NULL))
 OR NOT(t.mcp_writer_exit_verified<=>(NULL))
 OR NOT(t.mcp_retained_for_rollback<=>(NULL))
 OR NOT(BINARY t.mcp_package_version<=>BINARY (NULL))
 OR NOT(BINARY t.mcp_manifest_json<=>BINARY (NULL))
 OR NOT(BINARY t.mcp_manifest_sha256<=>BINARY (NULL))
 OR NOT(BINARY t.mcp_cleanup_request<=>BINARY (NULL))
 OR NOT(t.mcp_cleanup_expires_at<=>(NULL))
 OR NOT(BINARY t.mcp_reconcile_request<=>BINARY (NULL))
 OR NOT(t.mcp_reconcile_expires_at<=>(NULL))
 OR NOT(BINARY t.mcp_writer_evidence_code<=>BINARY (NULL))
 OR NOT(BINARY t.mcp_node_sha256<=>BINARY (NULL))
 OR NOT(t.mcp_controller_pid<=>(NULL))
 OR NOT(BINARY t.mcp_controller_started<=>BINARY (NULL))
 OR NOT(BINARY t.mcp_container_id<=>BINARY (NULL))
 OR NOT(BINARY t.mcp_container_started<=>BINARY (NULL))
 OR NOT(BINARY t.mcp_controller_pool_id<=>BINARY (NULL))
 OR NOT(BINARY t.mcp_native_pool_id<=>BINARY (NULL))
 OR NOT(BINARY t.mcp_action<=>BINARY (NULL))
 OR NOT(t.mcp_retention_protocol<=>(NULL))
 OR NOT(t.mcp_source_created_at<=>(NULL))
 OR NOT(t.mcp_source_updated_at<=>(NULL))
 OR NOT(BINARY t.mcp_source_utc_offset<=>BINARY (NULL))
 OR NOT(BINARY t.digest_legacy_row_json<=>BINARY (NULL));
INSERT INTO compact_report_guard SELECT IF(COUNT(*)=0,1,0) FROM `__SOURCE_SCHEMA__`.detection_report_audit a JOIN quality_report q ON BINARY q.report_id=BINARY a.report_id
 LEFT JOIN audit_event t ON BINARY t.event_id=BINARY (CONCAT('legacy-report-audit-',a.id))
 WHERE t.event_id IS NULL
 OR NOT(BINARY t.event_id<=>BINARY (CONCAT('legacy-report-audit-',a.id)))
 OR NOT(BINARY t.kind<=>BINARY ('QUALITY_REPORT'))
 OR NOT(t.owner_user_id<=>(q.owner_user_id))
 OR NOT(t.actor_user_id<=>(a.actor_user_id))
 OR NOT(BINARY t.resource_type<=>BINARY ('QUALITY_REPORT'))
 OR NOT(BINARY t.resource_id<=>BINARY (a.report_id))
 OR NOT(t.detection_model_id<=>(NULL))
 OR NOT(BINARY t.session_id<=>BINARY (NULL))
 OR NOT(t.message_id<=>(NULL))
 OR NOT(BINARY t.run_id<=>BINARY (NULL))
 OR NOT(BINARY t.journal_run_id<=>BINARY (NULL))
 OR NOT(t.sequence_no<=>(NULL))
 OR NOT(BINARY t.request_id<=>BINARY (NULL))
 OR NOT(BINARY t.action<=>BINARY (a.action))
 OR NOT(t.revision<=>(a.report_version))
 OR NOT(BINARY t.content_sha256<=>BINARY (a.snapshot_sha256))
 OR NOT(BINARY t.previous_sha256<=>BINARY (NULL))
 OR NOT(BINARY t.event_sha256<=>BINARY (NULL))
 OR NOT(t.quantity<=>(NULL))
 OR NOT(BINARY t.unit<=>BINARY (NULL))
 OR NOT(BINARY t.request_scope<=>BINARY (NULL))
 OR NOT(BINARY t.policy_version<=>BINARY (NULL))
 OR NOT(BINARY t.outcome<=>BINARY (NULL))
 OR NOT(t.observed_at<=>(NULL))
 OR NOT((t.occurred_at<=>IF(@compact_source_clock_unresolved,NULL,(CONVERT_TZ(a.created_at,@compact_validation_wall_offset,'+00:00')))))
 OR NOT(t.payload_version<=>(1))
 OR NOT(BINARY t.payload_json<=>BINARY (JSON_OBJECT('actorUsername',a.actor_username,'beforeStatus',a.before_status,'afterStatus',a.after_status,'reason',a.reason)))
 OR NOT(BINARY t.legacy_source<=>BINARY ('detection_report_audit'))
 OR NOT(BINARY t.legacy_key<=>BINARY (CAST(a.id AS CHAR)))
 OR NOT(BINARY t.call_id<=>BINARY (NULL))
 OR NOT(BINARY t.digest_legacy_detail_json<=>BINARY (NULL));
INSERT INTO compact_report_guard SELECT IF(COUNT(*)=0,1,0) FROM `__SOURCE_SCHEMA__`.detection_report_event_state s
 LEFT JOIN runtime_state t ON BINARY t.namespace=BINARY ('REPORT_EVENT_STATE') AND BINARY t.owner_id=BINARY (0) AND BINARY t.scope_key=BINARY (s.report_id)
 WHERE t.namespace IS NULL
 OR NOT(BINARY t.namespace<=>BINARY ('REPORT_EVENT_STATE'))
 OR NOT(t.owner_id<=>(0))
 OR NOT(BINARY t.scope_key<=>BINARY (s.report_id))
 OR NOT(BINARY t.session_id<=>BINARY (NULL))
 OR NOT(BINARY t.state_key<=>BINARY (NULL))
 OR NOT(t.revision<=>(1))
 OR NOT(BINARY t.state_code<=>BINARY (s.status))
 OR NOT(BINARY t.current_ref<=>BINARY (s.last_event_id))
 OR NOT(t.counter_value<=>(s.last_version))
 OR NOT(BINARY t.provider<=>BINARY (NULL))
 OR NOT(BINARY t.credential_sha256<=>BINARY (NULL))
 OR NOT(t.actor_user_id<=>(NULL))
 OR NOT(BINARY t.request_id<=>BINARY (NULL))
 OR NOT(t.window_started_at<=>(NULL))
 OR NOT(t.window_ends_at<=>(NULL))
 OR NOT(t.payload_version<=>(1))
 OR NOT(BINARY t.payload_json<=>BINARY (JSON_OBJECT('reportId',s.report_id,'lastEventId',s.last_event_id,'lastVersion',s.last_version,'status',s.status)))
 OR NOT(t.created_at<=>(NULL))
 OR NOT((t.updated_at<=>IF(@compact_source_clock_unresolved,NULL,(CONVERT_TZ(s.updated_at,@compact_validation_wall_offset,'+00:00')))));
INSERT INTO compact_report_guard SELECT IF(COUNT(*)=0,1,0) FROM `__SOURCE_SCHEMA__`.detection_report_command c JOIN quality_report q ON BINARY q.report_id=BINARY c.report_id LEFT JOIN workflow_instance clock_target ON BINARY clock_target.`legacy_source`<=>BINARY 'detection_report_command' AND BINARY clock_target.`legacy_key`<=>BINARY CAST(JSON_ARRAY(c.actor_user_id,c.request_id) AS CHAR) WHERE (clock_target.id IS NULL OR NOT(clock_target.legacy_clock_json<=>IF(@compact_source_clock_unresolved,JSON_OBJECT('protocol','doorhandle-legacy-clock-v1','status','UNRESOLVED','sourceTable','detection_report_command','sourceKey',JSON_OBJECT('actor_user_id',c.`actor_user_id`,'request_id',c.`request_id`),'sourceSnapshotSha256','__SOURCE_SNAPSHOT_SHA256__','sourceRowSha256',SHA2(CAST(JSON_OBJECT('actor_user_id',c.`actor_user_id`,'request_id',c.`request_id`,'command_sha256',c.`command_sha256`,'report_id',c.`report_id`,'response_json',c.`response_json`,'created_at',CAST(c.`created_at` AS CHAR CHARACTER SET utf8mb4)) AS CHAR CHARACTER SET utf8mb4),256),'sourceWallTimes',JSON_OBJECT('created_at',CAST(c.`created_at` AS CHAR))),NULL)) OR NOT(BINARY clock_target.`payload_json`<=>BINARY JSON_OBJECT('responseJson',c.response_json)) OR NOT(clock_target.`created_at`<=>IF(@compact_source_clock_unresolved,NULL,CONVERT_TZ(c.created_at,@compact_validation_wall_offset,'+00:00'))) OR NOT(clock_target.`updated_at`<=>IF(@compact_source_clock_unresolved,NULL,CONVERT_TZ(c.created_at,@compact_validation_wall_offset,'+00:00'))) OR NOT(clock_target.`finished_at`<=>IF(@compact_source_clock_unresolved,NULL,CONVERT_TZ(c.created_at,@compact_validation_wall_offset,'+00:00'))));
INSERT INTO compact_report_guard SELECT IF(COUNT(*)=0,1,0) FROM `__SOURCE_SCHEMA__`.detection_report_confirmation c JOIN quality_report q ON BINARY q.report_id=BINARY c.report_id LEFT JOIN workflow_instance clock_target ON BINARY clock_target.`legacy_source`<=>BINARY 'detection_report_confirmation' AND BINARY clock_target.`legacy_key`<=>BINARY c.token WHERE (clock_target.id IS NULL OR NOT(clock_target.legacy_clock_json<=>IF(@compact_source_clock_unresolved,JSON_OBJECT('protocol','doorhandle-legacy-clock-v1','status','UNRESOLVED','sourceTable','detection_report_confirmation','sourceKey',JSON_OBJECT('token',c.`token`),'sourceSnapshotSha256','__SOURCE_SNAPSHOT_SHA256__','sourceRowSha256',SHA2(CAST(JSON_OBJECT('token',c.`token`,'report_id',c.`report_id`,'actor_user_id',c.`actor_user_id`,'report_version',c.`report_version`,'snapshot_sha256',c.`snapshot_sha256`,'decision_sha256',c.`decision_sha256`,'expires_at',CAST(c.`expires_at` AS CHAR CHARACTER SET utf8mb4),'used_at',CAST(c.`used_at` AS CHAR CHARACTER SET utf8mb4)) AS CHAR CHARACTER SET utf8mb4),256),'sourceWallTimes',JSON_OBJECT('expires_at',CAST(c.`expires_at` AS CHAR),'used_at',CAST(c.`used_at` AS CHAR))),NULL)) OR NOT(clock_target.`expires_at`<=>IF(@compact_source_clock_unresolved,NULL,CONVERT_TZ(c.expires_at,@compact_validation_wall_offset,'+00:00'))) OR NOT(BINARY clock_target.`payload_json`<=>BINARY JSON_OBJECT('snapshotSha256',c.snapshot_sha256,'decisionSha256',c.decision_sha256)) OR NOT(clock_target.`created_at`<=>NULL) OR NOT(clock_target.`updated_at`<=>IF(@compact_source_clock_unresolved,NULL,CONVERT_TZ(c.used_at,@compact_validation_wall_offset,'+00:00'))) OR NOT(clock_target.`finished_at`<=>IF(@compact_source_clock_unresolved,NULL,CONVERT_TZ(c.used_at,@compact_validation_wall_offset,'+00:00'))));
INSERT INTO compact_report_guard SELECT IF(COUNT(*)=0,1,0) FROM `__SOURCE_SCHEMA__`.detection_report_agent_origin o JOIN quality_report q ON BINARY q.report_id=BINARY o.report_id LEFT JOIN workflow_instance clock_target ON BINARY clock_target.`legacy_source`<=>BINARY 'detection_report_agent_origin' AND BINARY clock_target.`legacy_key`<=>BINARY CAST(JSON_ARRAY(o.actor_user_id,o.request_id) AS CHAR) WHERE (clock_target.id IS NULL OR NOT(clock_target.legacy_clock_json<=>IF(@compact_source_clock_unresolved,JSON_OBJECT('protocol','doorhandle-legacy-clock-v1','status','UNRESOLVED','sourceTable','detection_report_agent_origin','sourceKey',JSON_OBJECT('actor_user_id',o.`actor_user_id`,'request_id',o.`request_id`),'sourceSnapshotSha256','__SOURCE_SNAPSHOT_SHA256__','sourceRowSha256',SHA2(CAST(JSON_OBJECT('actor_user_id',o.`actor_user_id`,'request_id',o.`request_id`,'report_id',o.`report_id`,'report_version',o.`report_version`,'run_id',o.`run_id`,'call_id',o.`call_id`,'tool_name',o.`tool_name`,'created_at',CAST(o.`created_at` AS CHAR CHARACTER SET utf8mb4)) AS CHAR CHARACTER SET utf8mb4),256),'sourceWallTimes',JSON_OBJECT('created_at',CAST(o.`created_at` AS CHAR))),NULL)) OR NOT(BINARY clock_target.`payload_json`<=>BINARY JSON_OBJECT('callId',o.call_id,'toolName',o.tool_name)) OR NOT(clock_target.`created_at`<=>IF(@compact_source_clock_unresolved,NULL,CONVERT_TZ(o.created_at,@compact_validation_wall_offset,'+00:00'))) OR NOT(clock_target.`updated_at`<=>IF(@compact_source_clock_unresolved,NULL,CONVERT_TZ(o.created_at,@compact_validation_wall_offset,'+00:00'))) OR NOT(clock_target.`finished_at`<=>IF(@compact_source_clock_unresolved,NULL,CONVERT_TZ(o.created_at,@compact_validation_wall_offset,'+00:00'))));
INSERT INTO compact_report_guard SELECT IF(COUNT(*)=0,1,0) FROM `__SOURCE_SCHEMA__`.detection_report_outbox e JOIN quality_report q ON BINARY q.report_id=BINARY e.report_id LEFT JOIN workflow_instance clock_target ON BINARY clock_target.`legacy_source`<=>BINARY 'detection_report_outbox' AND BINARY clock_target.`legacy_key`<=>BINARY e.event_id WHERE (clock_target.id IS NULL OR NOT(clock_target.legacy_clock_json<=>IF(@compact_source_clock_unresolved,JSON_OBJECT('protocol','doorhandle-legacy-clock-v1','status','UNRESOLVED','sourceTable','detection_report_outbox','sourceKey',JSON_OBJECT('event_id',e.`event_id`),'sourceSnapshotSha256','__SOURCE_SNAPSHOT_SHA256__','sourceRowSha256',SHA2(CAST(JSON_OBJECT('event_id',e.`event_id`,'report_id',e.`report_id`,'event_type',e.`event_type`,'payload_json',e.`payload_json`,'delivery_status',e.`delivery_status`,'created_at',CAST(e.`created_at` AS CHAR CHARACTER SET utf8mb4),'attempts',e.`attempts`,'next_attempt_at',CAST(e.`next_attempt_at` AS CHAR CHARACTER SET utf8mb4),'lease_token',e.`lease_token`,'lease_expires_at',CAST(e.`lease_expires_at` AS CHAR CHARACTER SET utf8mb4),'delivered_at',CAST(e.`delivered_at` AS CHAR CHARACTER SET utf8mb4),'last_error_code',e.`last_error_code`) AS CHAR CHARACTER SET utf8mb4),256),'sourceWallTimes',JSON_OBJECT('created_at',CAST(e.`created_at` AS CHAR),'next_attempt_at',CAST(e.`next_attempt_at` AS CHAR),'lease_expires_at',CAST(e.`lease_expires_at` AS CHAR),'delivered_at',CAST(e.`delivered_at` AS CHAR))),NULL)) OR NOT(clock_target.`lease_expires_at`<=>IF(@compact_source_clock_unresolved,NULL,CONVERT_TZ(e.lease_expires_at,@compact_validation_wall_offset,'+00:00'))) OR NOT(clock_target.`next_attempt_at`<=>IF(@compact_source_clock_unresolved,NULL,CONVERT_TZ(e.next_attempt_at,@compact_validation_wall_offset,'+00:00'))) OR NOT(BINARY clock_target.`payload_json`<=>BINARY JSON_OBJECT('eventType',e.event_type,'eventJson',e.payload_json)) OR NOT(clock_target.`created_at`<=>IF(@compact_source_clock_unresolved,NULL,CONVERT_TZ(e.created_at,@compact_validation_wall_offset,'+00:00'))) OR NOT(clock_target.`updated_at`<=>IF(@compact_source_clock_unresolved,NULL,COALESCE(CONVERT_TZ(e.delivered_at,@compact_validation_wall_offset,'+00:00'),CONVERT_TZ(e.created_at,@compact_validation_wall_offset,'+00:00')))) OR NOT(clock_target.`finished_at`<=>IF(@compact_source_clock_unresolved,NULL,CONVERT_TZ(e.delivered_at,@compact_validation_wall_offset,'+00:00'))));
INSERT INTO compact_report_guard SELECT IF(COUNT(*)=0,1,0) FROM `__SOURCE_SCHEMA__`.detection_report_event_receipt r JOIN quality_report q ON BINARY q.report_id=BINARY r.report_id JOIN `__SOURCE_SCHEMA__`.detection_report_outbox e ON BINARY e.event_id=BINARY r.event_id LEFT JOIN workflow_instance clock_target ON BINARY clock_target.`legacy_source`<=>BINARY 'detection_report_event_receipt' AND BINARY clock_target.`legacy_key`<=>BINARY r.event_id WHERE (clock_target.id IS NULL OR NOT(clock_target.legacy_clock_json<=>IF(@compact_source_clock_unresolved,JSON_OBJECT('protocol','doorhandle-legacy-clock-v1','status','UNRESOLVED','sourceTable','detection_report_event_receipt','sourceKey',JSON_OBJECT('event_id',r.`event_id`),'sourceSnapshotSha256','__SOURCE_SNAPSHOT_SHA256__','sourceRowSha256',SHA2(CAST(JSON_OBJECT('event_id',r.`event_id`,'report_id',r.`report_id`,'event_type',r.`event_type`,'report_version',r.`report_version`,'payload_sha256',r.`payload_sha256`,'consumed_at',CAST(r.`consumed_at` AS CHAR CHARACTER SET utf8mb4)) AS CHAR CHARACTER SET utf8mb4),256),'sourceWallTimes',JSON_OBJECT('consumed_at',CAST(r.`consumed_at` AS CHAR))),NULL)) OR NOT(BINARY clock_target.`payload_json`<=>BINARY JSON_OBJECT('eventType',r.event_type,'payloadSha256',r.payload_sha256)) OR NOT(clock_target.`created_at`<=>IF(@compact_source_clock_unresolved,NULL,CONVERT_TZ(r.consumed_at,@compact_validation_wall_offset,'+00:00'))) OR NOT(clock_target.`updated_at`<=>IF(@compact_source_clock_unresolved,NULL,CONVERT_TZ(r.consumed_at,@compact_validation_wall_offset,'+00:00'))) OR NOT(clock_target.`finished_at`<=>IF(@compact_source_clock_unresolved,NULL,CONVERT_TZ(r.consumed_at,@compact_validation_wall_offset,'+00:00'))));
INSERT INTO compact_report_guard SELECT IF(COUNT(*)=0,1,0) FROM `__SOURCE_SCHEMA__`.detection_report_audit a JOIN quality_report q ON BINARY q.report_id=BINARY a.report_id LEFT JOIN audit_event clock_target ON BINARY clock_target.`legacy_source`<=>BINARY 'detection_report_audit' AND BINARY clock_target.`legacy_key`<=>BINARY CAST(a.id AS CHAR) WHERE (clock_target.id IS NULL OR NOT(clock_target.legacy_clock_json<=>IF(@compact_source_clock_unresolved,JSON_OBJECT('protocol','doorhandle-legacy-clock-v1','status','UNRESOLVED','sourceTable','detection_report_audit','sourceKey',JSON_OBJECT('id',a.`id`),'sourceSnapshotSha256','__SOURCE_SNAPSHOT_SHA256__','sourceRowSha256',SHA2(CAST(JSON_OBJECT('id',a.`id`,'report_id',a.`report_id`,'actor_user_id',a.`actor_user_id`,'actor_username',a.`actor_username`,'action',a.`action`,'before_status',a.`before_status`,'after_status',a.`after_status`,'report_version',a.`report_version`,'reason',a.`reason`,'snapshot_sha256',a.`snapshot_sha256`,'created_at',CAST(a.`created_at` AS CHAR CHARACTER SET utf8mb4)) AS CHAR CHARACTER SET utf8mb4),256),'sourceWallTimes',JSON_OBJECT('created_at',CAST(a.`created_at` AS CHAR))),NULL)) OR NOT(clock_target.`occurred_at`<=>IF(@compact_source_clock_unresolved,NULL,CONVERT_TZ(a.created_at,@compact_validation_wall_offset,'+00:00'))) OR NOT(BINARY clock_target.`payload_json`<=>BINARY JSON_OBJECT('actorUsername',a.actor_username,'beforeStatus',a.before_status,'afterStatus',a.after_status,'reason',a.reason)));
INSERT INTO compact_report_guard SELECT IF(COUNT(*)=0,1,0) FROM `__SOURCE_SCHEMA__`.detection_report_event_state s LEFT JOIN runtime_state clock_target ON BINARY clock_target.`namespace`<=>BINARY 'REPORT_EVENT_STATE' AND BINARY clock_target.`owner_id`<=>BINARY 0 AND BINARY clock_target.`scope_key`<=>BINARY s.report_id WHERE (clock_target.namespace IS NULL OR NOT(clock_target.legacy_clock_json<=>IF(@compact_source_clock_unresolved,JSON_OBJECT('protocol','doorhandle-legacy-clock-v1','status','UNRESOLVED','sourceTable','detection_report_event_state','sourceKey',JSON_OBJECT('report_id',s.`report_id`),'sourceSnapshotSha256','__SOURCE_SNAPSHOT_SHA256__','sourceRowSha256',SHA2(CAST(JSON_OBJECT('report_id',s.`report_id`,'last_version',s.`last_version`,'status',s.`status`,'last_event_id',s.`last_event_id`,'updated_at',CAST(s.`updated_at` AS CHAR CHARACTER SET utf8mb4)) AS CHAR CHARACTER SET utf8mb4),256),'sourceWallTimes',JSON_OBJECT('updated_at',CAST(s.`updated_at` AS CHAR))),NULL)) OR NOT(BINARY clock_target.`payload_json`<=>BINARY JSON_OBJECT('reportId',s.report_id,'lastEventId',s.last_event_id,'lastVersion',s.last_version,'status',s.status)) OR NOT(clock_target.`created_at`<=>NULL) OR NOT(clock_target.`updated_at`<=>IF(@compact_source_clock_unresolved,NULL,CONVERT_TZ(s.updated_at,@compact_validation_wall_offset,'+00:00'))));
COMMIT;
DROP TEMPORARY TABLE compact_report_guard;
