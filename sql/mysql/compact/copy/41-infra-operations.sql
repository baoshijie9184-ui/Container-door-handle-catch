-- Generated explicit legacy-clock protocol by author_legacy_clock_copy.py.
-- validation_wall_offset is ONLY a zero-shift wall-value validator when unresolved.
-- It is never persisted as a source offset or used to manufacture UTC.
SET @compact_source_clock_unresolved=BINARY '__SOURCE_INFRA_LOG_OFFSET__'=BINARY 'UNRESOLVED';
SET @compact_validation_wall_offset=IF(@compact_source_clock_unresolved,'+00:00','__SOURCE_INFRA_LOG_OFFSET__');
SET NAMES utf8mb4;
CREATE TEMPORARY TABLE compact_infra_operation_guard(ok INT NOT NULL CHECK(ok=1)) ENGINE=InnoDB;
INSERT INTO compact_infra_operation_guard SELECT IF(DATABASE() IS NOT NULL AND BINARY DATABASE()<>BINARY '__SOURCE_SCHEMA__' AND @@FOREIGN_KEY_CHECKS=1 AND @@SESSION.sql_mode REGEXP '(^|,)(STRICT_TRANS_TABLES|STRICT_ALL_TABLES)(,|$)',1,0);
INSERT INTO compact_infra_operation_guard SELECT IF(REGEXP_LIKE(@compact_validation_wall_offset,'^[+-][0-9]{2}:[0-9]{2}$','c') AND CONVERT_TZ('2026-01-01',@compact_validation_wall_offset,'+00:00') IS NOT NULL,1,0);
INSERT INTO compact_infra_operation_guard SELECT IF(COUNT(DISTINCT privilege_type)=2,1,0) FROM information_schema.schema_privileges WHERE table_schema='__SOURCE_SCHEMA__' AND privilege_type IN ('SELECT','TRIGGER') AND grantee=CONCAT(QUOTE(SUBSTRING_INDEX(CURRENT_USER(),'@',1)),'@',QUOTE(SUBSTRING_INDEX(CURRENT_USER(),'@',-1)));
CREATE TEMPORARY TABLE compact_infra_operation_columns(column_name VARCHAR(64) PRIMARY KEY,column_type VARCHAR(64),nullable VARCHAR(3),collation_name VARCHAR(64),default_value VARCHAR(64),extra VARCHAR(64)) ENGINE=InnoDB;
INSERT INTO compact_infra_operation_columns VALUES
('id','bigint unsigned','NO',NULL,NULL,'auto_increment'),
('operator','varchar(64)','NO','utf8mb4_unicode_ci',NULL,''),
('action','varchar(32)','NO','utf8mb4_unicode_ci',NULL,''),
('resource_type','varchar(64)','NO','utf8mb4_unicode_ci',NULL,''),
('resource_id','varchar(128)','YES','utf8mb4_unicode_ci',NULL,''),
('request_method','varchar(16)','YES','utf8mb4_unicode_ci',NULL,''),
('request_path','varchar(512)','YES','utf8mb4_unicode_ci',NULL,''),
('change_summary','json','YES',NULL,NULL,''),
('result','varchar(16)','NO','utf8mb4_unicode_ci',NULL,''),
('client_ip','varchar(45)','YES','utf8mb4_unicode_ci',NULL,''),
('created_at','datetime','NO',NULL,'current_timestamp','default_generated');
INSERT INTO compact_infra_operation_guard SELECT IF(COUNT(*)=1,1,0) FROM information_schema.tables WHERE table_schema='__SOURCE_SCHEMA__' AND table_name='operation_audit_log' AND table_type='BASE TABLE' AND engine='InnoDB' AND table_collation='utf8mb4_unicode_ci';
INSERT INTO compact_infra_operation_guard SELECT IF(COUNT(*)=0,1,0) FROM information_schema.columns a LEFT JOIN compact_infra_operation_columns e ON BINARY e.column_name=BINARY a.column_name WHERE a.table_schema='__SOURCE_SCHEMA__' AND a.table_name='operation_audit_log' AND e.column_name IS NULL;
INSERT INTO compact_infra_operation_guard SELECT IF(COUNT(*)=0,1,0) FROM compact_infra_operation_columns e LEFT JOIN information_schema.columns a ON a.table_schema='__SOURCE_SCHEMA__' AND a.table_name='operation_audit_log' AND BINARY a.column_name=BINARY e.column_name WHERE a.column_name IS NULL OR NOT(BINARY LOWER(a.column_type)<=>BINARY e.column_type) OR NOT(BINARY a.is_nullable<=>BINARY e.nullable) OR NOT(BINARY a.collation_name<=>BINARY e.collation_name) OR NOT(BINARY a.character_set_name<=>BINARY IF(e.collation_name IS NULL,NULL,'utf8mb4')) OR NOT(BINARY LOWER(REPLACE(a.column_default,'()',''))<=>BINARY e.default_value) OR NOT(BINARY LOWER(REPLACE(a.extra,'()',''))<=>BINARY e.extra) OR a.generation_expression<>'';
CREATE TEMPORARY TABLE compact_infra_operation_indexes(index_name VARCHAR(64),index_position INT,column_name VARCHAR(64),non_unique INT,direction CHAR(1),PRIMARY KEY(index_name,index_position)) ENGINE=InnoDB;
INSERT INTO compact_infra_operation_indexes VALUES
('PRIMARY',1,'id',0,'A'),
('idx_audit_operator_time',1,'operator',1,'A'),
('idx_audit_operator_time',2,'created_at',1,'A'),
('idx_audit_resource_time',1,'resource_type',1,'A'),
('idx_audit_resource_time',2,'resource_id',1,'A'),
('idx_audit_resource_time',3,'created_at',1,'A'),
('idx_audit_created_at',1,'created_at',1,'A');
INSERT INTO compact_infra_operation_guard SELECT IF(COUNT(*)=0,1,0) FROM information_schema.statistics a LEFT JOIN compact_infra_operation_indexes e ON BINARY e.index_name=BINARY a.index_name AND e.index_position=a.seq_in_index WHERE a.table_schema='__SOURCE_SCHEMA__' AND a.table_name='operation_audit_log' AND e.column_name IS NULL;
INSERT INTO compact_infra_operation_guard SELECT IF(COUNT(*)=0,1,0) FROM compact_infra_operation_indexes e LEFT JOIN information_schema.statistics a ON a.table_schema='__SOURCE_SCHEMA__' AND a.table_name='operation_audit_log' AND BINARY a.index_name=BINARY e.index_name AND a.seq_in_index=e.index_position WHERE a.index_name IS NULL OR NOT(BINARY a.column_name<=>BINARY e.column_name) OR a.non_unique<>e.non_unique OR a.sub_part IS NOT NULL OR a.expression IS NOT NULL OR a.index_type<>'BTREE' OR a.is_visible<>'YES' OR NOT(BINARY a.collation<=>BINARY e.direction);
INSERT INTO compact_infra_operation_guard SELECT IF(COUNT(*)=0,1,0) FROM information_schema.triggers WHERE event_object_schema='__SOURCE_SCHEMA__' AND event_object_table='operation_audit_log';
INSERT INTO compact_infra_operation_guard SELECT IF(COUNT(*)=0,1,0) FROM information_schema.table_constraints WHERE table_schema='__SOURCE_SCHEMA__' AND table_name='operation_audit_log' AND constraint_type='CHECK';
INSERT INTO compact_infra_operation_guard SELECT IF(COUNT(*)=0,1,0) FROM information_schema.referential_constraints WHERE constraint_schema='__SOURCE_SCHEMA__' AND table_name='operation_audit_log';
INSERT INTO compact_infra_operation_guard SELECT NOT EXISTS(SELECT 1 FROM `__SOURCE_SCHEMA__`.operation_audit_log s WHERE CONVERT_TZ(s.created_at,@compact_validation_wall_offset,'+00:00') IS NULL OR NOT(TIMESTAMPDIFF(SECOND,CONVERT_TZ(s.created_at,@compact_validation_wall_offset,'+00:00'),s.created_at)<=>(IF(LEFT(@compact_validation_wall_offset,1)='-',-1,1)*(CAST(SUBSTRING(@compact_validation_wall_offset,2,2) AS UNSIGNED)*3600+CAST(SUBSTRING(@compact_validation_wall_offset,5,2) AS UNSIGNED)*60))));
START TRANSACTION;
INSERT INTO compact_infra_operation_guard SELECT IF(NOT @compact_source_clock_unresolved OR REGEXP_LIKE('__SOURCE_SNAPSHOT_SHA256__','^[a-f0-9]{64}$','c'),1,0);
INSERT INTO compact_infra_operation_guard SELECT NOT EXISTS(SELECT 1 FROM audit_event WHERE kind='INFRA_OPERATION' OR legacy_source='operation_audit_log');
INSERT INTO audit_event(event_id,kind,resource_type,resource_id,action,outcome,occurred_at,payload_version,payload_json,legacy_source,legacy_key,legacy_clock_json) SELECT CONCAT('legacy-infra-operation-',s.id),'INFRA_OPERATION',s.resource_type,s.resource_id,s.action,s.result,IF(@compact_source_clock_unresolved,NULL,CONVERT_TZ(s.created_at,@compact_validation_wall_offset,'+00:00')),1,JSON_OBJECT('operatorName',s.operator,'requestMethod',s.request_method,'requestPath',s.request_path,'changeSummary',s.change_summary,'changeSummarySqlNull',CAST(IF(s.change_summary IS NULL,'true','false') AS JSON),'clientIp',s.client_ip,'legacyCreatedAt',DATE_FORMAT(s.created_at,'%Y-%m-%dT%H:%i:%s')),'operation_audit_log',CAST(s.id AS CHAR),IF(@compact_source_clock_unresolved,JSON_OBJECT('protocol','doorhandle-legacy-clock-v1','status','UNRESOLVED','sourceTable','operation_audit_log','sourceKey',JSON_OBJECT('id',s.`id`),'sourceSnapshotSha256','__SOURCE_SNAPSHOT_SHA256__','sourceRowSha256',SHA2(CAST(JSON_OBJECT('id',s.`id`,'operator',s.`operator`,'action',s.`action`,'resource_type',s.`resource_type`,'resource_id',s.`resource_id`,'request_method',s.`request_method`,'request_path',s.`request_path`,'change_summary',CAST(s.`change_summary` AS CHAR CHARACTER SET utf8mb4),'result',s.`result`,'client_ip',s.`client_ip`,'created_at',CAST(s.`created_at` AS CHAR CHARACTER SET utf8mb4)) AS CHAR CHARACTER SET utf8mb4),256),'sourceWallTimes',JSON_OBJECT('created_at',CAST(s.`created_at` AS CHAR))),NULL) FROM `__SOURCE_SCHEMA__`.operation_audit_log s ORDER BY s.id;
INSERT INTO compact_infra_operation_guard SELECT (SELECT COUNT(*) FROM `__SOURCE_SCHEMA__`.operation_audit_log)=(SELECT COUNT(*) FROM audit_event WHERE kind='INFRA_OPERATION');
INSERT INTO compact_infra_operation_guard SELECT NOT EXISTS(SELECT 1 FROM `__SOURCE_SCHEMA__`.operation_audit_log s LEFT JOIN audit_event a ON BINARY a.legacy_source=BINARY 'operation_audit_log' AND BINARY a.legacy_key=BINARY CAST(s.id AS CHAR)
 WHERE a.id IS NULL OR NOT(BINARY a.legacy_source<=>BINARY 'operation_audit_log') OR NOT(BINARY a.legacy_key<=>BINARY CAST(s.id AS CHAR)) OR NOT(BINARY a.kind<=>BINARY 'INFRA_OPERATION') OR NOT(BINARY a.event_id<=>BINARY CONCAT('legacy-infra-operation-',s.id))
 OR NOT(BINARY a.resource_type<=>BINARY s.resource_type) OR NOT(BINARY a.resource_id<=>BINARY s.resource_id) OR NOT(BINARY a.action<=>BINARY s.action) OR NOT(BINARY a.outcome<=>BINARY s.result)
 OR a.owner_user_id IS NOT NULL OR a.actor_user_id IS NOT NULL OR a.request_id IS NOT NULL OR a.request_scope IS NOT NULL OR a.detection_model_id IS NOT NULL
 OR a.revision IS NOT NULL OR a.session_id IS NOT NULL OR a.run_id IS NOT NULL OR a.sequence_no IS NOT NULL OR a.content_sha256 IS NOT NULL
 OR a.message_id IS NOT NULL OR a.journal_run_id IS NOT NULL OR a.previous_sha256 IS NOT NULL OR a.event_sha256 IS NOT NULL
 OR a.quantity IS NOT NULL OR a.unit IS NOT NULL OR a.policy_version IS NOT NULL OR a.observed_at IS NOT NULL
 OR a.execution_message_id IS NOT NULL OR a.execution_run_id IS NOT NULL OR a.research_export_run_id IS NOT NULL
 OR a.observation_model_id IS NOT NULL OR a.observation_request_id IS NOT NULL OR a.operation_scope IS NOT NULL OR a.operation_domain IS NOT NULL OR a.operation_result IS NOT NULL
 OR a.legacy_model_attempt_id IS NOT NULL OR a.legacy_attempt_model_id IS NOT NULL
 OR NOT(a.payload_version<=>1) OR NOT((a.occurred_at<=>IF(@compact_source_clock_unresolved,NULL,CONVERT_TZ(s.created_at,@compact_validation_wall_offset,'+00:00')))) OR NOT(BINARY a.payload_json<=>BINARY JSON_OBJECT('operatorName',s.operator,'requestMethod',s.request_method,'requestPath',s.request_path,'changeSummary',s.change_summary,'changeSummarySqlNull',CAST(IF(s.change_summary IS NULL,'true','false') AS JSON),'clientIp',s.client_ip,'legacyCreatedAt',DATE_FORMAT(s.created_at,'%Y-%m-%dT%H:%i:%s'))));
INSERT INTO compact_infra_operation_guard SELECT IF(COUNT(*)=0,1,0) FROM `__SOURCE_SCHEMA__`.operation_audit_log s LEFT JOIN audit_event clock_target ON BINARY clock_target.`legacy_source`<=>BINARY 'operation_audit_log' AND BINARY clock_target.`legacy_key`<=>BINARY CAST(s.id AS CHAR) WHERE (clock_target.id IS NULL OR NOT(clock_target.legacy_clock_json<=>IF(@compact_source_clock_unresolved,JSON_OBJECT('protocol','doorhandle-legacy-clock-v1','status','UNRESOLVED','sourceTable','operation_audit_log','sourceKey',JSON_OBJECT('id',s.`id`),'sourceSnapshotSha256','__SOURCE_SNAPSHOT_SHA256__','sourceRowSha256',SHA2(CAST(JSON_OBJECT('id',s.`id`,'operator',s.`operator`,'action',s.`action`,'resource_type',s.`resource_type`,'resource_id',s.`resource_id`,'request_method',s.`request_method`,'request_path',s.`request_path`,'change_summary',CAST(s.`change_summary` AS CHAR CHARACTER SET utf8mb4),'result',s.`result`,'client_ip',s.`client_ip`,'created_at',CAST(s.`created_at` AS CHAR CHARACTER SET utf8mb4)) AS CHAR CHARACTER SET utf8mb4),256),'sourceWallTimes',JSON_OBJECT('created_at',CAST(s.`created_at` AS CHAR))),NULL)) OR NOT(BINARY clock_target.`occurred_at`<=>BINARY IF(@compact_source_clock_unresolved,NULL,CONVERT_TZ(s.created_at,@compact_validation_wall_offset,'+00:00'))) OR NOT(BINARY clock_target.`payload_json`<=>BINARY JSON_OBJECT('operatorName',s.operator,'requestMethod',s.request_method,'requestPath',s.request_path,'changeSummary',s.change_summary,'changeSummarySqlNull',CAST(IF(s.change_summary IS NULL,'true','false') AS JSON),'clientIp',s.client_ip,'legacyCreatedAt',DATE_FORMAT(s.created_at,'%Y-%m-%dT%H:%i:%s'))));
COMMIT;
DROP TEMPORARY TABLE compact_infra_operation_indexes;
DROP TEMPORARY TABLE compact_infra_operation_columns;
DROP TEMPORARY TABLE compact_infra_operation_guard;
