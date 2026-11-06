-- Candidate, NOT EXECUTED. Distinct source/target schemas on one admitted isolated ECS server.
-- Isolated EMPTY domain target only, after agent_run copy; source writers must be stopped.
-- Closed source metadata contract: actual migration V33/V35. Unknown fields or changed declarations abort.
-- Validate __SOURCE_SCHEMA__ as an identifier and supply the observed source DATETIME
-- offset as __SOURCE_EXPORT_OFFSET__. Stop at first error and ROLLBACK on this connection.
SET NAMES utf8mb4;
CREATE TEMPORARY TABLE compact_research_export_guard(ok TINYINT NOT NULL CHECK(ok=1)) ENGINE=InnoDB;
INSERT INTO compact_research_export_guard SELECT IF(DATABASE() IS NOT NULL AND BINARY DATABASE()<>BINARY '__SOURCE_SCHEMA__'
 AND @@FOREIGN_KEY_CHECKS=1 AND @@SESSION.sql_mode REGEXP '(^|,)(STRICT_TRANS_TABLES|STRICT_ALL_TABLES)(,|$)',1,0);
INSERT INTO compact_research_export_guard SELECT IF(REGEXP_LIKE('__SOURCE_EXPORT_OFFSET__','^[+-][0-9]{2}:[0-9]{2}$','c') AND CONVERT_TZ('2026-01-01','__SOURCE_EXPORT_OFFSET__','+00:00') IS NOT NULL,1,0);
-- Metadata visibility is mandatory: a hidden source trigger must not look like an absent trigger.
INSERT INTO compact_research_export_guard SELECT IF(COUNT(DISTINCT privilege_type)=2,1,0)
 FROM information_schema.schema_privileges WHERE table_schema='__SOURCE_SCHEMA__' AND privilege_type IN ('SELECT','TRIGGER')
 AND grantee=CONCAT(QUOTE(SUBSTRING_INDEX(CURRENT_USER(),'@',1)),'@',QUOTE(SUBSTRING_INDEX(CURRENT_USER(),'@',-1)));
CREATE TEMPORARY TABLE compact_research_export_columns(table_name VARCHAR(64),column_name VARCHAR(64),column_type VARCHAR(64),nullable VARCHAR(3),collation_name VARCHAR(64),default_value VARCHAR(64),extra VARCHAR(64),PRIMARY KEY(table_name,column_name)) ENGINE=InnoDB;
INSERT INTO compact_research_export_columns VALUES
('agent_research_export_audit','id','bigint unsigned','NO',NULL,NULL,'auto_increment'),
('agent_research_export_audit','export_id','varchar(36)','NO','utf8mb4_bin',NULL,''),
('agent_research_export_audit','run_id','varchar(36)','NO','utf8mb4_bin',NULL,''),
('agent_research_export_audit','user_id','bigint','NO',NULL,NULL,''),
('agent_research_export_audit','format_version','int','NO',NULL,NULL,''),
('agent_research_export_audit','source_count','int','NO',NULL,NULL,''),
('agent_research_export_audit','expired_source_count','int','NO',NULL,NULL,''),
('agent_research_export_audit','payload_bytes','int','NO',NULL,NULL,''),
('agent_research_export_audit','payload_sha256','char(64)','NO','utf8mb4_bin',NULL,''),
('agent_research_export_audit','created_at','datetime(6)','NO',NULL,'current_timestamp(6)','default_generated'),
('agent_research_export_limit','user_id','bigint','NO',NULL,NULL,''),
('agent_research_export_limit','window_ends_at','datetime(6)','NO',NULL,'current_timestamp(6)','default_generated'),
('agent_research_export_limit','export_count','int','NO',NULL,'0','');
INSERT INTO compact_research_export_guard SELECT IF(COUNT(*)=2,1,0) FROM information_schema.tables
 WHERE table_schema='__SOURCE_SCHEMA__' AND table_name IN ('agent_research_export_audit','agent_research_export_limit') AND table_type='BASE TABLE' AND engine='InnoDB' AND table_collation='utf8mb4_bin';
INSERT INTO compact_research_export_guard SELECT IF(COUNT(*)=0,1,0) FROM information_schema.columns a LEFT JOIN compact_research_export_columns e ON BINARY e.table_name=BINARY a.table_name AND BINARY e.column_name=BINARY a.column_name
 WHERE a.table_schema='__SOURCE_SCHEMA__' AND a.table_name IN ('agent_research_export_audit','agent_research_export_limit') AND e.column_name IS NULL;
INSERT INTO compact_research_export_guard SELECT IF(COUNT(*)=0,1,0) FROM compact_research_export_columns e LEFT JOIN information_schema.columns a ON a.table_schema='__SOURCE_SCHEMA__' AND BINARY a.table_name=BINARY e.table_name AND BINARY a.column_name=BINARY e.column_name
 WHERE a.column_name IS NULL OR NOT(BINARY LOWER(a.column_type)<=>BINARY e.column_type) OR NOT(BINARY a.is_nullable<=>BINARY e.nullable)
 OR NOT(BINARY a.collation_name<=>BINARY e.collation_name) OR NOT(BINARY a.character_set_name<=>BINARY IF(e.collation_name IS NULL,NULL,'utf8mb4'))
 OR NOT(BINARY LOWER(a.column_default)<=>BINARY e.default_value) OR NOT(BINARY LOWER(a.extra)<=>BINARY e.extra) OR a.generation_expression<>'';
CREATE TEMPORARY TABLE compact_research_export_indexes(table_name VARCHAR(64),index_name VARCHAR(64),index_position INT,column_name VARCHAR(64),non_unique INT,PRIMARY KEY(table_name,index_name,index_position)) ENGINE=InnoDB;
INSERT INTO compact_research_export_indexes VALUES
('agent_research_export_audit','PRIMARY',1,'id',0),
('agent_research_export_audit','uk_research_export',1,'export_id',0),
('agent_research_export_audit','idx_research_export_owner',1,'user_id',1),
('agent_research_export_audit','idx_research_export_owner',2,'run_id',1),
('agent_research_export_audit','idx_research_export_owner',3,'id',1),
('agent_research_export_limit','PRIMARY',1,'user_id',0),
('agent_research_export_audit','fk_research_export_run',1,'run_id',1);
INSERT INTO compact_research_export_guard SELECT IF(COUNT(*)=0,1,0) FROM information_schema.statistics a LEFT JOIN compact_research_export_indexes e
 ON BINARY e.table_name=BINARY a.table_name AND BINARY e.index_name=BINARY a.index_name AND e.index_position=a.seq_in_index
 WHERE a.table_schema='__SOURCE_SCHEMA__' AND a.table_name IN ('agent_research_export_audit','agent_research_export_limit') AND e.column_name IS NULL;
INSERT INTO compact_research_export_guard SELECT IF(COUNT(*)=0,1,0) FROM compact_research_export_indexes e LEFT JOIN information_schema.statistics a
 ON a.table_schema='__SOURCE_SCHEMA__' AND BINARY a.table_name=BINARY e.table_name AND BINARY a.index_name=BINARY e.index_name AND a.seq_in_index=e.index_position
 WHERE a.index_name IS NULL OR NOT(BINARY a.column_name<=>BINARY e.column_name) OR a.non_unique<>e.non_unique
 OR a.sub_part IS NOT NULL OR a.expression IS NOT NULL OR a.index_type<>'BTREE' OR a.is_visible<>'YES' OR a.collation<>'A';
INSERT INTO compact_research_export_guard SELECT IF(COUNT(*)=0,1,0) FROM information_schema.triggers
 WHERE event_object_schema='__SOURCE_SCHEMA__' AND event_object_table IN ('agent_research_export_audit','agent_research_export_limit');
-- V33 has exactly one non-composite, same-schema run FK; V35 has no FK/CHECK.
INSERT INTO compact_research_export_guard SELECT IF(COUNT(*)=0,1,0) FROM information_schema.table_constraints
 WHERE table_schema='__SOURCE_SCHEMA__' AND table_name IN ('agent_research_export_audit','agent_research_export_limit') AND constraint_type='CHECK';
INSERT INTO compact_research_export_guard SELECT IF(COUNT(*)=1,1,0) FROM information_schema.referential_constraints
 WHERE constraint_schema='__SOURCE_SCHEMA__' AND table_name IN ('agent_research_export_audit','agent_research_export_limit');
INSERT INTO compact_research_export_guard SELECT IF(COUNT(*)=1,1,0) FROM information_schema.key_column_usage k
 JOIN information_schema.referential_constraints r ON r.constraint_schema=k.constraint_schema AND r.constraint_name=k.constraint_name AND r.table_name=k.table_name
 WHERE k.table_schema='__SOURCE_SCHEMA__' AND k.table_name='agent_research_export_audit' AND k.constraint_name='fk_research_export_run'
 AND k.column_name='run_id' AND k.ordinal_position=1 AND k.position_in_unique_constraint=1
 AND k.referenced_table_schema='__SOURCE_SCHEMA__' AND k.referenced_table_name='agent_run' AND k.referenced_column_name='run_id'
 AND r.update_rule IN ('RESTRICT','NO ACTION') AND r.delete_rule IN ('RESTRICT','NO ACTION');
INSERT INTO compact_research_export_guard SELECT IF(COUNT(*)=1,1,0) FROM information_schema.key_column_usage
 WHERE table_schema='__SOURCE_SCHEMA__' AND table_name='agent_research_export_audit' AND referenced_table_name IS NOT NULL;
-- Complete agent_run declarations belong to copy/25-agent-runs.sql; this slice additionally checks its authorization projection.
INSERT INTO compact_research_export_guard SELECT IF(COUNT(*)=2,1,0) FROM information_schema.columns
 WHERE table_schema='__SOURCE_SCHEMA__' AND table_name='agent_run' AND is_nullable='NO'
 AND ((column_name='run_id' AND column_type='varchar(36)' AND collation_name='utf8mb4_bin') OR (column_name='user_id' AND column_type='bigint'));
START TRANSACTION;
INSERT INTO compact_research_export_guard SELECT
 NOT EXISTS(SELECT 1 FROM audit_event WHERE kind='RESEARCH_EXPORT')
 AND NOT EXISTS(SELECT 1 FROM runtime_state WHERE namespace='RESEARCH_EXPORT_LIMIT');
INSERT INTO compact_research_export_guard SELECT NOT EXISTS(
 SELECT 1 FROM `__SOURCE_SCHEMA__`.agent_research_export_audit e
 LEFT JOIN `__SOURCE_SCHEMA__`.agent_run s ON BINARY s.run_id=BINARY e.run_id AND s.user_id=e.user_id
 LEFT JOIN agent_run t ON BINARY t.run_id=BINARY e.run_id AND t.user_id=e.user_id
 WHERE s.run_id IS NULL OR t.run_id IS NULL OR e.user_id<=0 OR CHAR_LENGTH(e.export_id)=0
 OR e.format_version<1 OR e.source_count<0 OR e.expired_source_count<0 OR e.payload_bytes<0
 OR e.payload_sha256 NOT REGEXP '^[a-f0-9]{64}$'
 OR CONVERT_TZ(e.created_at,'__SOURCE_EXPORT_OFFSET__','+00:00') IS NULL OR NOT(TIMESTAMPDIFF(MICROSECOND,CONVERT_TZ(e.created_at,'__SOURCE_EXPORT_OFFSET__','+00:00'),e.created_at)<=>((IF(LEFT('__SOURCE_EXPORT_OFFSET__',1)='-',-1,1)*(CAST(SUBSTRING('__SOURCE_EXPORT_OFFSET__',2,2) AS UNSIGNED)*3600+CAST(SUBSTRING('__SOURCE_EXPORT_OFFSET__',5,2) AS UNSIGNED)*60))*1000000)));
INSERT INTO compact_research_export_guard SELECT NOT EXISTS(
 SELECT 1 FROM `__SOURCE_SCHEMA__`.agent_research_export_limit l WHERE l.user_id<=0 OR l.export_count<0
 OR CONVERT_TZ(l.window_ends_at,'__SOURCE_EXPORT_OFFSET__','+00:00') IS NULL OR NOT(TIMESTAMPDIFF(MICROSECOND,CONVERT_TZ(l.window_ends_at,'__SOURCE_EXPORT_OFFSET__','+00:00'),l.window_ends_at)<=>((IF(LEFT('__SOURCE_EXPORT_OFFSET__',1)='-',-1,1)*(CAST(SUBSTRING('__SOURCE_EXPORT_OFFSET__',2,2) AS UNSIGNED)*3600+CAST(SUBSTRING('__SOURCE_EXPORT_OFFSET__',5,2) AS UNSIGNED)*60))*1000000)));

-- No excerpts, URLs or export bytes enter the receipt. The source export UUID stays globally unique.
INSERT INTO audit_event(event_id,kind,owner_user_id,actor_user_id,resource_type,resource_id,run_id,
 request_scope,request_id,action,content_sha256,quantity,unit,occurred_at,payload_version,payload_json,legacy_source,legacy_key)
SELECT CONCAT('research-export-',e.id),'RESEARCH_EXPORT',e.user_id,e.user_id,'RESEARCH_EXPORT',e.export_id,e.run_id,
 'RESEARCH_EXPORT',e.export_id,'EXPORT',e.payload_sha256,e.payload_bytes,'BYTES',
 CONVERT_TZ(e.created_at,'__SOURCE_EXPORT_OFFSET__','+00:00'),1,
 JSON_OBJECT('formatVersion',e.format_version,'sourceCount',e.source_count,'expiredSourceCount',e.expired_source_count),
 'agent_research_export_audit',CAST(e.id AS CHAR)
 FROM `__SOURCE_SCHEMA__`.agent_research_export_audit e ORDER BY e.id;

-- The old counter had no creation/update timestamps. Unknown facts remain NULL; the actual window is retained.
INSERT INTO runtime_state(namespace,owner_id,scope_key,revision,counter_value,window_ends_at,created_at,updated_at)
SELECT 'RESEARCH_EXPORT_LIMIT',l.user_id,'',0,l.export_count,
 CONVERT_TZ(l.window_ends_at,'__SOURCE_EXPORT_OFFSET__','+00:00'),NULL,NULL
 FROM `__SOURCE_SCHEMA__`.agent_research_export_limit l ORDER BY l.user_id;

INSERT INTO compact_research_export_guard SELECT
 (SELECT COUNT(*) FROM `__SOURCE_SCHEMA__`.agent_research_export_audit)=(SELECT COUNT(*) FROM audit_event WHERE kind='RESEARCH_EXPORT')
 AND (SELECT COUNT(*) FROM `__SOURCE_SCHEMA__`.agent_research_export_limit)=(SELECT COUNT(*) FROM runtime_state WHERE namespace='RESEARCH_EXPORT_LIMIT');
INSERT INTO compact_research_export_guard SELECT NOT EXISTS(
 SELECT 1 FROM `__SOURCE_SCHEMA__`.agent_research_export_audit e
 LEFT JOIN audit_event a ON BINARY a.kind=BINARY 'RESEARCH_EXPORT' AND BINARY a.legacy_source=BINARY 'agent_research_export_audit' AND BINARY a.legacy_key=BINARY CAST(e.id AS CHAR)
 WHERE a.id IS NULL OR NOT(a.owner_user_id<=>e.user_id) OR NOT(a.actor_user_id<=>e.user_id)
 OR NOT(BINARY a.event_id<=>BINARY CONCAT('research-export-',e.id)) OR NOT(a.payload_version<=>1)
 OR NOT(BINARY a.resource_id<=>BINARY e.export_id) OR NOT(BINARY a.request_id<=>BINARY e.export_id) OR NOT(BINARY a.request_scope<=>BINARY 'RESEARCH_EXPORT')
 OR NOT(BINARY a.run_id<=>BINARY e.run_id) OR NOT(BINARY a.content_sha256<=>BINARY e.payload_sha256)
 OR NOT(a.quantity<=>e.payload_bytes) OR NOT(BINARY a.unit<=>BINARY 'BYTES') OR NOT(BINARY a.resource_type<=>BINARY 'RESEARCH_EXPORT') OR NOT(BINARY a.action<=>BINARY 'EXPORT')
 OR NOT(BINARY a.payload_json<=>BINARY JSON_OBJECT('formatVersion',e.format_version,'sourceCount',e.source_count,'expiredSourceCount',e.expired_source_count))
 OR NOT(a.occurred_at<=>CONVERT_TZ(e.created_at,'__SOURCE_EXPORT_OFFSET__','+00:00')));
INSERT INTO compact_research_export_guard SELECT NOT EXISTS(
 SELECT 1 FROM `__SOURCE_SCHEMA__`.agent_research_export_limit l
 LEFT JOIN runtime_state r ON BINARY r.namespace=BINARY 'RESEARCH_EXPORT_LIMIT' AND r.owner_id=l.user_id AND BINARY r.scope_key=BINARY ''
 WHERE r.owner_id IS NULL OR NOT(r.counter_value<=>l.export_count)
 OR NOT(r.window_ends_at<=>CONVERT_TZ(l.window_ends_at,'__SOURCE_EXPORT_OFFSET__','+00:00'))
 OR r.created_at IS NOT NULL OR r.updated_at IS NOT NULL OR NOT(r.revision<=>0));
-- Reject unrelated public state injected by a target trigger; row counts alone are insufficient.
INSERT INTO compact_research_export_guard SELECT NOT EXISTS(SELECT 1 FROM audit_event WHERE (kind='RESEARCH_EXPORT') AND (detection_model_id IS NOT NULL OR session_id IS NOT NULL OR message_id IS NOT NULL OR journal_run_id IS NOT NULL OR sequence_no IS NOT NULL OR revision IS NOT NULL OR previous_sha256 IS NOT NULL OR event_sha256 IS NOT NULL OR policy_version IS NOT NULL OR outcome IS NOT NULL OR observed_at IS NOT NULL));
INSERT INTO compact_research_export_guard SELECT NOT EXISTS(SELECT 1 FROM runtime_state WHERE (namespace='RESEARCH_EXPORT_LIMIT') AND (session_id IS NOT NULL OR state_key IS NOT NULL OR state_code IS NOT NULL OR current_ref IS NOT NULL OR provider IS NOT NULL OR credential_sha256 IS NOT NULL OR actor_user_id IS NOT NULL OR request_id IS NOT NULL OR window_started_at IS NOT NULL OR NOT(payload_version<=>1) OR payload_json IS NOT NULL));
COMMIT;
DROP TEMPORARY TABLE compact_research_export_guard;
DROP TEMPORARY TABLE compact_research_export_columns;
DROP TEMPORARY TABLE compact_research_export_indexes;
