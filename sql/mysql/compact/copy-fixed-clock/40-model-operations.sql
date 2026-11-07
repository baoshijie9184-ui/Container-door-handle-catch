-- Candidate, NOT EXECUTED. Distinct stopped source/target schemas on one admitted ECS MySQL server.
-- Validated __SOURCE_SCHEMA__ and observed __SOURCE_MODEL_LOG_OFFSET__ are required; never guess a host timezone.
-- Abort at first error and ROLLBACK on this exact connection. No source mutation or compatibility objects.
SET NAMES utf8mb4;
CREATE TEMPORARY TABLE compact_model_operation_guard(ok INT NOT NULL CHECK(ok=1)) ENGINE=InnoDB;
INSERT INTO compact_model_operation_guard SELECT IF(DATABASE() IS NOT NULL AND BINARY DATABASE()<>BINARY '__SOURCE_SCHEMA__' AND @@FOREIGN_KEY_CHECKS=1 AND @@SESSION.sql_mode REGEXP '(^|,)(STRICT_TRANS_TABLES|STRICT_ALL_TABLES)(,|$)',1,0);
INSERT INTO compact_model_operation_guard SELECT IF(REGEXP_LIKE('__SOURCE_MODEL_LOG_OFFSET__','^[+-][0-9]{2}:[0-9]{2}$','c') AND CONVERT_TZ('2026-01-01','__SOURCE_MODEL_LOG_OFFSET__','+00:00') IS NOT NULL,1,0);
INSERT INTO compact_model_operation_guard SELECT IF(COUNT(DISTINCT privilege_type)=2,1,0) FROM information_schema.schema_privileges WHERE table_schema='__SOURCE_SCHEMA__' AND privilege_type IN ('SELECT','TRIGGER') AND grantee=CONCAT(QUOTE(SUBSTRING_INDEX(CURRENT_USER(),'@',1)),'@',QUOTE(SUBSTRING_INDEX(CURRENT_USER(),'@',-1)));
CREATE TEMPORARY TABLE compact_model_operation_columns(column_name VARCHAR(64) PRIMARY KEY,column_type VARCHAR(64),nullable VARCHAR(3),collation_name VARCHAR(64),default_value VARCHAR(64),extra VARCHAR(64)) ENGINE=InnoDB;
INSERT INTO compact_model_operation_columns VALUES
('id','bigint','NO',NULL,NULL,'auto_increment'),
('model_id','int','NO',NULL,NULL,''),
('operation_type','varchar(32)','NO','utf8mb4_unicode_ci',NULL,''),
('operator','varchar(64)','YES','utf8mb4_unicode_ci',NULL,''),
('operation_time','datetime','NO',NULL,'current_timestamp','default_generated'),
('remark','varchar(255)','YES','utf8mb4_unicode_ci',NULL,'');
INSERT INTO compact_model_operation_guard SELECT IF(COUNT(*)=1,1,0) FROM information_schema.tables WHERE table_schema='__SOURCE_SCHEMA__' AND table_name='model_operation_log' AND table_type='BASE TABLE' AND engine='InnoDB' AND table_collation='utf8mb4_unicode_ci';
INSERT INTO compact_model_operation_guard SELECT IF(COUNT(*)=0,1,0) FROM information_schema.columns a LEFT JOIN compact_model_operation_columns e ON BINARY e.column_name=BINARY a.column_name WHERE a.table_schema='__SOURCE_SCHEMA__' AND a.table_name='model_operation_log' AND e.column_name IS NULL;
INSERT INTO compact_model_operation_guard SELECT IF(COUNT(*)=0,1,0) FROM compact_model_operation_columns e LEFT JOIN information_schema.columns a ON a.table_schema='__SOURCE_SCHEMA__' AND a.table_name='model_operation_log' AND BINARY a.column_name=BINARY e.column_name WHERE a.column_name IS NULL OR NOT(BINARY LOWER(a.column_type)<=>BINARY e.column_type) OR NOT(BINARY a.is_nullable<=>BINARY e.nullable) OR NOT(BINARY a.collation_name<=>BINARY e.collation_name) OR NOT(BINARY a.character_set_name<=>BINARY IF(e.collation_name IS NULL,NULL,'utf8mb4')) OR NOT(BINARY LOWER(REPLACE(a.column_default,'()',''))<=>BINARY e.default_value) OR NOT(BINARY LOWER(REPLACE(a.extra,'()',''))<=>BINARY e.extra) OR a.generation_expression<>'';
CREATE TEMPORARY TABLE compact_model_operation_indexes(index_name VARCHAR(64),index_position INT,column_name VARCHAR(64),non_unique INT,direction CHAR(1),PRIMARY KEY(index_name,index_position)) ENGINE=InnoDB;
INSERT INTO compact_model_operation_indexes VALUES
('PRIMARY',1,'id',0,'A'),
('idx_model_operation_log_model_id',1,'model_id',1,'A'),
('idx_model_operation_log_time',1,'operation_time',1,'A'),
('idx_model_operation_log_model_time',1,'model_id',1,'A'),
('idx_model_operation_log_model_time',2,'operation_time',1,'D'),
('idx_model_operation_log_model_time',3,'id',1,'D');
INSERT INTO compact_model_operation_guard SELECT IF(COUNT(*)=0,1,0) FROM information_schema.statistics a LEFT JOIN compact_model_operation_indexes e ON BINARY e.index_name=BINARY a.index_name AND e.index_position=a.seq_in_index WHERE a.table_schema='__SOURCE_SCHEMA__' AND a.table_name='model_operation_log' AND e.column_name IS NULL;
INSERT INTO compact_model_operation_guard SELECT IF(COUNT(*)=0,1,0) FROM compact_model_operation_indexes e LEFT JOIN information_schema.statistics a ON a.table_schema='__SOURCE_SCHEMA__' AND a.table_name='model_operation_log' AND BINARY a.index_name=BINARY e.index_name AND a.seq_in_index=e.index_position WHERE a.index_name IS NULL OR NOT(BINARY a.column_name<=>BINARY e.column_name) OR a.non_unique<>e.non_unique OR a.sub_part IS NOT NULL OR a.expression IS NOT NULL OR a.index_type<>'BTREE' OR a.is_visible<>'YES' OR NOT(BINARY a.collation<=>BINARY e.direction);
INSERT INTO compact_model_operation_guard SELECT IF(COUNT(*)=0,1,0) FROM information_schema.triggers WHERE event_object_schema='__SOURCE_SCHEMA__' AND event_object_table='model_operation_log';
INSERT INTO compact_model_operation_guard SELECT IF(COUNT(*)=0,1,0) FROM information_schema.table_constraints WHERE table_schema='__SOURCE_SCHEMA__' AND table_name='model_operation_log' AND constraint_type='CHECK';
-- Exact V3 + V7 contract. The live signed model reference preserves both CASCADE actions.
INSERT INTO compact_model_operation_guard SELECT IF(COUNT(*)=1,1,0) FROM information_schema.referential_constraints WHERE constraint_schema='__SOURCE_SCHEMA__' AND table_name='model_operation_log';
INSERT INTO compact_model_operation_guard SELECT IF(COUNT(*)=1,1,0) FROM information_schema.key_column_usage k JOIN information_schema.referential_constraints r ON r.constraint_schema=k.constraint_schema AND r.constraint_name=k.constraint_name AND r.table_name=k.table_name WHERE k.table_schema='__SOURCE_SCHEMA__' AND k.table_name='model_operation_log' AND k.constraint_name='fk_model_operation_log_model' AND k.column_name='model_id' AND k.ordinal_position=1 AND k.position_in_unique_constraint=1 AND k.referenced_table_schema='__SOURCE_SCHEMA__' AND k.referenced_table_name='model_management' AND k.referenced_column_name='model_id' AND r.update_rule='CASCADE' AND r.delete_rule='CASCADE';
INSERT INTO compact_model_operation_guard SELECT IF(COUNT(*)=1,1,0) FROM information_schema.key_column_usage WHERE table_schema='__SOURCE_SCHEMA__' AND table_name='model_operation_log' AND referenced_table_name IS NOT NULL;
INSERT INTO compact_model_operation_guard SELECT NOT EXISTS(SELECT 1 FROM `__SOURCE_SCHEMA__`.model_operation_log s LEFT JOIN `__SOURCE_SCHEMA__`.model_management p ON p.model_id=s.model_id LEFT JOIN model_management t ON t.model_id=s.model_id WHERE p.model_id IS NULL OR t.model_id IS NULL OR CONVERT_TZ(s.operation_time,'__SOURCE_MODEL_LOG_OFFSET__','+00:00') IS NULL OR NOT(TIMESTAMPDIFF(SECOND,CONVERT_TZ(s.operation_time,'__SOURCE_MODEL_LOG_OFFSET__','+00:00'),s.operation_time)<=>(IF(LEFT('__SOURCE_MODEL_LOG_OFFSET__',1)='-',-1,1)*(CAST(SUBSTRING('__SOURCE_MODEL_LOG_OFFSET__',2,2) AS UNSIGNED)*3600+CAST(SUBSTRING('__SOURCE_MODEL_LOG_OFFSET__',5,2) AS UNSIGNED)*60))));
-- MySQL may return an out-of-range DATETIME unchanged; require the actual signed offset above.
START TRANSACTION;
INSERT INTO compact_model_operation_guard SELECT NOT EXISTS(SELECT 1 FROM audit_event WHERE kind='DETECTION_MODEL_OPERATION' OR legacy_source='model_operation_log');
INSERT INTO audit_event(event_id,kind,resource_type,detection_model_id,action,occurred_at,payload_version,payload_json,legacy_source,legacy_key)
SELECT CONCAT('legacy-model-operation-',s.id),'DETECTION_MODEL_OPERATION','DETECTION_MODEL',s.model_id,s.operation_type,
 CONVERT_TZ(s.operation_time,'__SOURCE_MODEL_LOG_OFFSET__','+00:00'),1,
 JSON_OBJECT('operatorName',s.operator,'remark',s.remark,'legacyOperationTime',DATE_FORMAT(s.operation_time,'%Y-%m-%dT%H:%i:%s')),
 'model_operation_log',CAST(s.id AS CHAR) FROM `__SOURCE_SCHEMA__`.model_operation_log s ORDER BY s.id;
INSERT INTO compact_model_operation_guard SELECT (SELECT COUNT(*) FROM `__SOURCE_SCHEMA__`.model_operation_log)=(SELECT COUNT(*) FROM audit_event WHERE kind='DETECTION_MODEL_OPERATION');
INSERT INTO compact_model_operation_guard SELECT NOT EXISTS(SELECT 1 FROM `__SOURCE_SCHEMA__`.model_operation_log s LEFT JOIN audit_event a ON BINARY a.legacy_source=BINARY 'model_operation_log' AND BINARY a.legacy_key=BINARY CAST(s.id AS CHAR)
 WHERE a.id IS NULL OR NOT(BINARY a.legacy_source<=>BINARY 'model_operation_log') OR NOT(BINARY a.legacy_key<=>BINARY CAST(s.id AS CHAR)) OR NOT(BINARY a.kind<=>BINARY 'DETECTION_MODEL_OPERATION') OR NOT(BINARY a.event_id<=>BINARY CONCAT('legacy-model-operation-',s.id))
 OR NOT(a.detection_model_id<=>s.model_id) OR NOT(BINARY a.resource_type<=>BINARY 'DETECTION_MODEL') OR a.resource_id IS NOT NULL OR NOT(BINARY a.action<=>BINARY s.operation_type)
 OR a.owner_user_id IS NOT NULL OR a.actor_user_id IS NOT NULL OR a.request_id IS NOT NULL OR a.request_scope IS NOT NULL OR a.outcome IS NOT NULL
 OR a.revision IS NOT NULL OR a.session_id IS NOT NULL OR a.run_id IS NOT NULL OR a.sequence_no IS NOT NULL OR a.content_sha256 IS NOT NULL
 OR a.message_id IS NOT NULL OR a.journal_run_id IS NOT NULL OR a.previous_sha256 IS NOT NULL OR a.event_sha256 IS NOT NULL
 OR a.quantity IS NOT NULL OR a.unit IS NOT NULL OR a.policy_version IS NOT NULL OR a.observed_at IS NOT NULL
 OR a.execution_message_id IS NOT NULL OR a.execution_run_id IS NOT NULL OR a.research_export_run_id IS NOT NULL
 OR a.observation_model_id IS NOT NULL OR a.observation_request_id IS NOT NULL OR a.operation_scope IS NOT NULL OR a.operation_domain IS NOT NULL OR a.operation_result IS NOT NULL
 OR a.legacy_model_attempt_id IS NOT NULL OR a.legacy_attempt_model_id IS NOT NULL
 OR NOT(a.payload_version<=>1) OR NOT(a.occurred_at<=>CONVERT_TZ(s.operation_time,'__SOURCE_MODEL_LOG_OFFSET__','+00:00'))
 OR NOT(BINARY a.payload_json<=>BINARY JSON_OBJECT('operatorName',s.operator,'remark',s.remark,'legacyOperationTime',DATE_FORMAT(s.operation_time,'%Y-%m-%dT%H:%i:%s'))));
COMMIT;
DROP TEMPORARY TABLE compact_model_operation_indexes;
DROP TEMPORARY TABLE compact_model_operation_columns;
DROP TEMPORARY TABLE compact_model_operation_guard;
