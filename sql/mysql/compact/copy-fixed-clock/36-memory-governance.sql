-- Candidate, NOT EXECUTED. Distinct source/target schemas on one admitted isolated ECS server.
-- Isolated EMPTY domain target only, source writers stopped; never alter or delete source memory.
-- Closed source metadata contract: actual migration V26. Unknown fields or changed declarations abort.
-- Render validated __SOURCE_SCHEMA__ and observed __SOURCE_MEMORY_OFFSET__; no host-zone inference.
-- Stop at first failure and ROLLBACK on the same connection. Mem0 bodies remain outside these tables.
SET NAMES utf8mb4;
CREATE TEMPORARY TABLE compact_memory_guard(ok TINYINT NOT NULL CHECK(ok=1)) ENGINE=InnoDB;
INSERT INTO compact_memory_guard SELECT IF(DATABASE() IS NOT NULL AND BINARY DATABASE()<>BINARY '__SOURCE_SCHEMA__'
 AND @@FOREIGN_KEY_CHECKS=1 AND @@SESSION.sql_mode REGEXP '(^|,)(STRICT_TRANS_TABLES|STRICT_ALL_TABLES)(,|$)',1,0);
INSERT INTO compact_memory_guard SELECT IF(REGEXP_LIKE('__SOURCE_MEMORY_OFFSET__','^[+-][0-9]{2}:[0-9]{2}$','c') AND CONVERT_TZ('2026-01-01','__SOURCE_MEMORY_OFFSET__','+00:00') IS NOT NULL,1,0);
-- Metadata visibility is mandatory: a hidden source trigger must not look like an absent trigger.
INSERT INTO compact_memory_guard SELECT IF(COUNT(DISTINCT privilege_type)=2,1,0)
 FROM information_schema.schema_privileges WHERE table_schema='__SOURCE_SCHEMA__' AND privilege_type IN ('SELECT','TRIGGER')
 AND grantee=CONCAT(QUOTE(SUBSTRING_INDEX(CURRENT_USER(),'@',1)),'@',QUOTE(SUBSTRING_INDEX(CURRENT_USER(),'@',-1)));
CREATE TEMPORARY TABLE compact_memory_columns(table_name VARCHAR(64),column_name VARCHAR(64),column_type VARCHAR(64),nullable VARCHAR(3),collation_name VARCHAR(64),default_value VARCHAR(64),extra VARCHAR(64),PRIMARY KEY(table_name,column_name)) ENGINE=InnoDB;
INSERT INTO compact_memory_columns VALUES
('agent_memory_preference','owner_user_id','bigint','NO',NULL,NULL,''),
('agent_memory_preference','read_enabled','tinyint(1)','NO',NULL,'1',''),
('agent_memory_preference','save_enabled','tinyint(1)','NO',NULL,'1',''),
('agent_memory_preference','revision','int','NO',NULL,'0',''),
('agent_memory_preference','updated_at','datetime','NO',NULL,NULL,''),
('agent_memory_audit','id','bigint','NO',NULL,NULL,'auto_increment'),
('agent_memory_audit','owner_user_id','bigint','NO',NULL,NULL,''),
('agent_memory_audit','action_name','varchar(32)','NO','utf8mb4_bin',NULL,''),
('agent_memory_audit','outcome','varchar(32)','NO','utf8mb4_bin',NULL,''),
('agent_memory_audit','request_key','varchar(64)','YES','utf8mb4_bin',NULL,''),
('agent_memory_audit','memory_id','varchar(64)','YES','utf8mb4_bin',NULL,''),
('agent_memory_audit','content_digest','char(64)','YES','utf8mb4_bin',NULL,''),
('agent_memory_audit','preference_revision','int','YES',NULL,NULL,''),
('agent_memory_audit','read_enabled','tinyint(1)','YES',NULL,NULL,''),
('agent_memory_audit','save_enabled','tinyint(1)','YES',NULL,NULL,''),
('agent_memory_audit','created_at','datetime','NO',NULL,NULL,''),
('agent_memory_audit','updated_at','datetime','NO',NULL,NULL,'');
INSERT INTO compact_memory_guard SELECT IF(COUNT(*)=2,1,0) FROM information_schema.tables
 WHERE table_schema='__SOURCE_SCHEMA__' AND table_name IN ('agent_memory_preference','agent_memory_audit') AND table_type='BASE TABLE' AND engine='InnoDB' AND table_collation='utf8mb4_bin';
INSERT INTO compact_memory_guard SELECT IF(COUNT(*)=0,1,0) FROM information_schema.columns a LEFT JOIN compact_memory_columns e ON BINARY e.table_name=BINARY a.table_name AND BINARY e.column_name=BINARY a.column_name
 WHERE a.table_schema='__SOURCE_SCHEMA__' AND a.table_name IN ('agent_memory_preference','agent_memory_audit') AND e.column_name IS NULL;
INSERT INTO compact_memory_guard SELECT IF(COUNT(*)=0,1,0) FROM compact_memory_columns e LEFT JOIN information_schema.columns a ON a.table_schema='__SOURCE_SCHEMA__' AND BINARY a.table_name=BINARY e.table_name AND BINARY a.column_name=BINARY e.column_name
 WHERE a.column_name IS NULL OR NOT(BINARY LOWER(a.column_type)<=>BINARY e.column_type) OR NOT(BINARY a.is_nullable<=>BINARY e.nullable)
 OR NOT(BINARY a.collation_name<=>BINARY e.collation_name) OR NOT(BINARY a.character_set_name<=>BINARY IF(e.collation_name IS NULL,NULL,'utf8mb4'))
 OR NOT(BINARY LOWER(a.column_default)<=>BINARY e.default_value) OR NOT(BINARY LOWER(a.extra)<=>BINARY e.extra) OR a.generation_expression<>'';
CREATE TEMPORARY TABLE compact_memory_indexes(table_name VARCHAR(64),index_name VARCHAR(64),index_position INT,column_name VARCHAR(64),non_unique INT,PRIMARY KEY(table_name,index_name,index_position)) ENGINE=InnoDB;
INSERT INTO compact_memory_indexes VALUES
('agent_memory_preference','PRIMARY',1,'owner_user_id',0),
('agent_memory_audit','PRIMARY',1,'id',0),
('agent_memory_audit','uk_memory_request',1,'owner_user_id',0),
('agent_memory_audit','uk_memory_request',2,'request_key',0),
('agent_memory_audit','idx_memory_audit_owner',1,'owner_user_id',1),
('agent_memory_audit','idx_memory_audit_owner',2,'id',1);
INSERT INTO compact_memory_guard SELECT IF(COUNT(*)=0,1,0) FROM information_schema.statistics a LEFT JOIN compact_memory_indexes e
 ON BINARY e.table_name=BINARY a.table_name AND BINARY e.index_name=BINARY a.index_name AND e.index_position=a.seq_in_index
 WHERE a.table_schema='__SOURCE_SCHEMA__' AND a.table_name IN ('agent_memory_preference','agent_memory_audit') AND e.column_name IS NULL;
INSERT INTO compact_memory_guard SELECT IF(COUNT(*)=0,1,0) FROM compact_memory_indexes e LEFT JOIN information_schema.statistics a
 ON a.table_schema='__SOURCE_SCHEMA__' AND BINARY a.table_name=BINARY e.table_name AND BINARY a.index_name=BINARY e.index_name AND a.seq_in_index=e.index_position
 WHERE a.index_name IS NULL OR NOT(BINARY a.column_name<=>BINARY e.column_name) OR a.non_unique<>e.non_unique
 OR a.sub_part IS NOT NULL OR a.expression IS NOT NULL OR a.index_type<>'BTREE' OR a.is_visible<>'YES' OR a.collation<>'A';
INSERT INTO compact_memory_guard SELECT IF(COUNT(*)=0,1,0) FROM information_schema.triggers
 WHERE event_object_schema='__SOURCE_SCHEMA__' AND event_object_table IN ('agent_memory_preference','agent_memory_audit');
-- V26 has only the declared primary/unique keys; an unknown FK or CHECK changes the source contract.
INSERT INTO compact_memory_guard SELECT IF(COUNT(*)=0,1,0) FROM information_schema.table_constraints
 WHERE table_schema='__SOURCE_SCHEMA__' AND table_name IN ('agent_memory_preference','agent_memory_audit') AND constraint_type IN ('FOREIGN KEY','CHECK');
START TRANSACTION;
INSERT INTO compact_memory_guard SELECT
 NOT EXISTS(SELECT 1 FROM runtime_state WHERE namespace='MEMORY_PREFERENCE')
 AND NOT EXISTS(SELECT 1 FROM workflow_instance WHERE kind='MEMORY_MUTATION')
 AND NOT EXISTS(SELECT 1 FROM audit_event WHERE kind IN ('MEMORY_PREFERENCE','MEMORY_OPERATION'));
INSERT INTO compact_memory_guard SELECT NOT EXISTS(
 SELECT 1 FROM `__SOURCE_SCHEMA__`.agent_memory_preference p WHERE p.owner_user_id<=0 OR p.revision<0
 OR p.read_enabled NOT IN (0,1) OR p.save_enabled NOT IN (0,1)
 OR CONVERT_TZ(p.updated_at,'__SOURCE_MEMORY_OFFSET__','+00:00') IS NULL OR NOT(TIMESTAMPDIFF(MICROSECOND,CONVERT_TZ(p.updated_at,'__SOURCE_MEMORY_OFFSET__','+00:00'),p.updated_at)<=>((IF(LEFT('__SOURCE_MEMORY_OFFSET__',1)='-',-1,1)*(CAST(SUBSTRING('__SOURCE_MEMORY_OFFSET__',2,2) AS SIGNED)*3600+CAST(SUBSTRING('__SOURCE_MEMORY_OFFSET__',5,2) AS SIGNED)*60))*1000000)));
INSERT INTO compact_memory_guard SELECT NOT EXISTS(
 SELECT 1 FROM `__SOURCE_SCHEMA__`.agent_memory_audit a WHERE a.owner_user_id<=0
 OR BINARY a.action_name NOT IN (BINARY 'PREFERENCE_CHANGED',BINARY 'DELETE',BINARY 'UPDATE',BINARY 'AUTOSAVE',BINARY 'REVIEW_DECISION',BINARY 'LIFECYCLE')
 OR BINARY a.outcome NOT IN (BINARY 'PENDING',BINARY 'DISPATCHED',BINARY 'SUCCEEDED',BINARY 'REJECTED',BINARY 'UNKNOWN')
 OR CONVERT_TZ(a.created_at,'__SOURCE_MEMORY_OFFSET__','+00:00') IS NULL OR NOT(TIMESTAMPDIFF(MICROSECOND,CONVERT_TZ(a.created_at,'__SOURCE_MEMORY_OFFSET__','+00:00'),a.created_at)<=>((IF(LEFT('__SOURCE_MEMORY_OFFSET__',1)='-',-1,1)*(CAST(SUBSTRING('__SOURCE_MEMORY_OFFSET__',2,2) AS SIGNED)*3600+CAST(SUBSTRING('__SOURCE_MEMORY_OFFSET__',5,2) AS SIGNED)*60))*1000000))
 OR CONVERT_TZ(a.updated_at,'__SOURCE_MEMORY_OFFSET__','+00:00') IS NULL OR NOT(TIMESTAMPDIFF(MICROSECOND,CONVERT_TZ(a.updated_at,'__SOURCE_MEMORY_OFFSET__','+00:00'),a.updated_at)<=>((IF(LEFT('__SOURCE_MEMORY_OFFSET__',1)='-',-1,1)*(CAST(SUBSTRING('__SOURCE_MEMORY_OFFSET__',2,2) AS SIGNED)*3600+CAST(SUBSTRING('__SOURCE_MEMORY_OFFSET__',5,2) AS SIGNED)*60))*1000000))
 OR (a.action_name='PREFERENCE_CHANGED' AND (a.outcome<>'SUCCEEDED' OR a.request_key IS NOT NULL
   OR a.memory_id IS NOT NULL OR a.content_digest IS NOT NULL OR a.preference_revision IS NULL OR a.preference_revision<0
   OR a.read_enabled IS NULL OR a.read_enabled NOT IN (0,1) OR a.save_enabled IS NULL OR a.save_enabled NOT IN (0,1)))
 OR (a.action_name<>'PREFERENCE_CHANGED' AND (a.request_key IS NULL OR CHAR_LENGTH(a.request_key)=0
   OR a.content_digest IS NULL OR a.content_digest NOT REGEXP '^[a-f0-9]{64}$'
   OR a.preference_revision IS NOT NULL OR a.read_enabled IS NOT NULL OR a.save_enabled IS NOT NULL
   OR (a.action_name='AUTOSAVE' AND a.memory_id IS NOT NULL)
   OR (a.action_name<>'AUTOSAVE' AND (a.memory_id IS NULL OR CHAR_LENGTH(a.memory_id)=0)))));

INSERT INTO runtime_state(namespace,owner_id,scope_key,revision,payload_version,payload_json,created_at,updated_at)
SELECT 'MEMORY_PREFERENCE',p.owner_user_id,'',p.revision,1,
 JSON_OBJECT('readEnabled',CAST(IF(p.read_enabled,'true','false') AS JSON),'saveEnabled',CAST(IF(p.save_enabled,'true','false') AS JSON)),
 NULL,CONVERT_TZ(p.updated_at,'__SOURCE_MEMORY_OFFSET__','+00:00')
 FROM `__SOURCE_SCHEMA__`.agent_memory_preference p ORDER BY p.owner_user_id;

-- Request identity spans all mutation actions, exactly as the original owner/request unique key.
-- Revision 0 is the new concurrency counter; the old table did not record transition revisions.
INSERT INTO workflow_instance(workflow_id,kind,idempotency_scope,request_id,request_sha256,owner_user_id,
 resource_type,resource_id,status,revision,fence,payload_version,payload_json,created_at,updated_at,finished_at,legacy_source,legacy_key)
SELECT CONCAT('memory-mutation-',a.id),'MEMORY_MUTATION',CONCAT('OWNER:',a.owner_user_id),a.request_key,a.content_digest,a.owner_user_id,
 'MEMORY',a.memory_id,a.outcome,0,0,1,JSON_OBJECT('action',a.action_name),
 CONVERT_TZ(a.created_at,'__SOURCE_MEMORY_OFFSET__','+00:00'),CONVERT_TZ(a.updated_at,'__SOURCE_MEMORY_OFFSET__','+00:00'),
 IF(a.outcome IN ('SUCCEEDED','REJECTED'),CONVERT_TZ(a.updated_at,'__SOURCE_MEMORY_OFFSET__','+00:00'),NULL),
 'agent_memory_audit',CAST(a.id AS CHAR) FROM `__SOURCE_SCHEMA__`.agent_memory_audit a WHERE a.action_name<>'PREFERENCE_CHANGED' ORDER BY a.id;

-- One immutable snapshot of the old final row; never fabricate missing historical state transitions.
-- Legacy mutation timestamps are retained on the workflow, preference audit timestamps in this explicit receipt.
INSERT INTO audit_event(event_id,kind,owner_user_id,resource_type,resource_id,request_id,action,revision,
 content_sha256,outcome,occurred_at,payload_version,payload_json,legacy_source,legacy_key)
SELECT CONCAT('memory-audit-',a.id),IF(a.action_name='PREFERENCE_CHANGED','MEMORY_PREFERENCE','MEMORY_OPERATION'),a.owner_user_id,
 IF(a.action_name='PREFERENCE_CHANGED','MEMORY_PREFERENCE','MEMORY_MUTATION'),
 IF(a.action_name='PREFERENCE_CHANGED',CAST(a.owner_user_id AS CHAR),CONCAT('memory-mutation-',a.id)),a.request_key,a.action_name,
 IF(a.action_name='PREFERENCE_CHANGED',a.preference_revision,0),a.content_digest,a.outcome,
 CONVERT_TZ(IF(a.action_name='PREFERENCE_CHANGED',a.created_at,a.updated_at),'__SOURCE_MEMORY_OFFSET__','+00:00'),1,
 IF(a.action_name='PREFERENCE_CHANGED',JSON_OBJECT('readEnabled',CAST(IF(a.read_enabled,'true','false') AS JSON),
   'saveEnabled',CAST(IF(a.save_enabled,'true','false') AS JSON),
   'legacyUpdatedAt',DATE_FORMAT(CONVERT_TZ(a.updated_at,'__SOURCE_MEMORY_OFFSET__','+00:00'),'%Y-%m-%dT%H:%i:%s.%f')),
   JSON_OBJECT('legacySnapshot',CAST('true' AS JSON))),
 'agent_memory_audit',CAST(a.id AS CHAR) FROM `__SOURCE_SCHEMA__`.agent_memory_audit a ORDER BY a.id;

INSERT INTO compact_memory_guard SELECT
 (SELECT COUNT(*) FROM `__SOURCE_SCHEMA__`.agent_memory_preference)=(SELECT COUNT(*) FROM runtime_state WHERE namespace='MEMORY_PREFERENCE')
 AND (SELECT COUNT(*) FROM `__SOURCE_SCHEMA__`.agent_memory_audit WHERE action_name<>'PREFERENCE_CHANGED')=(SELECT COUNT(*) FROM workflow_instance WHERE kind='MEMORY_MUTATION')
 AND (SELECT COUNT(*) FROM `__SOURCE_SCHEMA__`.agent_memory_audit)=(SELECT COUNT(*) FROM audit_event WHERE kind IN ('MEMORY_PREFERENCE','MEMORY_OPERATION'));
INSERT INTO compact_memory_guard SELECT NOT EXISTS(
 SELECT 1 FROM `__SOURCE_SCHEMA__`.agent_memory_preference p LEFT JOIN runtime_state r
 ON BINARY r.namespace=BINARY 'MEMORY_PREFERENCE' AND r.owner_id=p.owner_user_id AND BINARY r.scope_key=BINARY ''
 WHERE r.owner_id IS NULL OR NOT(r.revision<=>p.revision)
 OR NOT(r.payload_version<=>1)
 OR NOT(BINARY r.payload_json<=>BINARY JSON_OBJECT('readEnabled',CAST(IF(p.read_enabled,'true','false') AS JSON),'saveEnabled',CAST(IF(p.save_enabled,'true','false') AS JSON)))
 OR r.created_at IS NOT NULL OR NOT(r.updated_at<=>CONVERT_TZ(p.updated_at,'__SOURCE_MEMORY_OFFSET__','+00:00')));
INSERT INTO compact_memory_guard SELECT NOT EXISTS(
 SELECT 1 FROM `__SOURCE_SCHEMA__`.agent_memory_audit a LEFT JOIN workflow_instance w
 ON BINARY w.kind=BINARY 'MEMORY_MUTATION' AND BINARY w.legacy_source=BINARY 'agent_memory_audit' AND BINARY w.legacy_key=BINARY CAST(a.id AS CHAR)
 WHERE a.action_name<>'PREFERENCE_CHANGED' AND (w.id IS NULL OR NOT(w.owner_user_id<=>a.owner_user_id)
 OR NOT(BINARY w.workflow_id<=>BINARY CONCAT('memory-mutation-',a.id)) OR NOT(BINARY w.idempotency_scope<=>BINARY CONCAT('OWNER:',a.owner_user_id))
 OR NOT(BINARY w.request_id<=>BINARY a.request_key) OR NOT(BINARY w.request_sha256<=>BINARY a.content_digest)
 OR NOT(BINARY w.resource_id<=>BINARY a.memory_id) OR NOT(BINARY w.status<=>BINARY a.outcome)
 OR NOT(BINARY w.resource_type<=>BINARY 'MEMORY') OR w.actor_user_id IS NOT NULL
 OR NOT(w.revision<=>0) OR NOT(w.fence<=>0) OR NOT(w.payload_version<=>1)
 OR NOT(BINARY w.payload_json<=>BINARY JSON_OBJECT('action',a.action_name))
 OR NOT(w.created_at<=>CONVERT_TZ(a.created_at,'__SOURCE_MEMORY_OFFSET__','+00:00'))
 OR NOT(w.updated_at<=>CONVERT_TZ(a.updated_at,'__SOURCE_MEMORY_OFFSET__','+00:00'))
 OR NOT(w.finished_at<=>IF(a.outcome IN ('SUCCEEDED','REJECTED'),CONVERT_TZ(a.updated_at,'__SOURCE_MEMORY_OFFSET__','+00:00'),NULL))));
INSERT INTO compact_memory_guard SELECT NOT EXISTS(
 SELECT 1 FROM `__SOURCE_SCHEMA__`.agent_memory_audit s LEFT JOIN audit_event a
 ON a.kind IN ('MEMORY_PREFERENCE','MEMORY_OPERATION') AND BINARY a.legacy_source=BINARY 'agent_memory_audit' AND BINARY a.legacy_key=BINARY CAST(s.id AS CHAR)
 WHERE a.id IS NULL OR NOT(a.owner_user_id<=>s.owner_user_id) OR NOT(BINARY a.action<=>BINARY s.action_name) OR NOT(BINARY a.outcome<=>BINARY s.outcome)
 OR NOT(BINARY a.event_id<=>BINARY CONCAT('memory-audit-',s.id)) OR a.actor_user_id IS NOT NULL OR NOT(a.payload_version<=>1)
 OR NOT(BINARY a.request_id<=>BINARY s.request_key) OR NOT(BINARY a.content_sha256<=>BINARY s.content_digest)
 OR (s.action_name='PREFERENCE_CHANGED' AND (NOT(BINARY a.kind<=>BINARY 'MEMORY_PREFERENCE') OR NOT(BINARY a.resource_type<=>BINARY 'MEMORY_PREFERENCE') OR NOT(BINARY a.resource_id<=>BINARY CAST(s.owner_user_id AS CHAR))
   OR NOT(a.revision<=>s.preference_revision) OR NOT(a.occurred_at<=>CONVERT_TZ(s.created_at,'__SOURCE_MEMORY_OFFSET__','+00:00'))
   OR NOT(BINARY a.payload_json<=>BINARY JSON_OBJECT('readEnabled',CAST(IF(s.read_enabled,'true','false') AS JSON),'saveEnabled',CAST(IF(s.save_enabled,'true','false') AS JSON),
     'legacyUpdatedAt',DATE_FORMAT(CONVERT_TZ(s.updated_at,'__SOURCE_MEMORY_OFFSET__','+00:00'),'%Y-%m-%dT%H:%i:%s.%f')))))
 OR (s.action_name<>'PREFERENCE_CHANGED' AND (NOT(BINARY a.kind<=>BINARY 'MEMORY_OPERATION') OR NOT(BINARY a.resource_type<=>BINARY 'MEMORY_MUTATION') OR NOT(BINARY a.resource_id<=>BINARY CONCAT('memory-mutation-',s.id))
   OR NOT(a.revision<=>0) OR NOT(a.occurred_at<=>CONVERT_TZ(s.updated_at,'__SOURCE_MEMORY_OFFSET__','+00:00'))
   OR NOT(BINARY a.payload_json<=>BINARY JSON_OBJECT('legacySnapshot',CAST('true' AS JSON))))));
-- Reject unrelated public state injected by a target trigger; row counts alone are insufficient.
INSERT INTO compact_memory_guard SELECT NOT EXISTS(SELECT 1 FROM audit_event WHERE (kind IN ('MEMORY_PREFERENCE','MEMORY_OPERATION')) AND (actor_user_id IS NOT NULL OR detection_model_id IS NOT NULL OR session_id IS NOT NULL OR message_id IS NOT NULL OR run_id IS NOT NULL OR journal_run_id IS NOT NULL OR sequence_no IS NOT NULL OR previous_sha256 IS NOT NULL OR event_sha256 IS NOT NULL OR quantity IS NOT NULL OR unit IS NOT NULL OR request_scope IS NOT NULL OR policy_version IS NOT NULL OR observed_at IS NOT NULL));
INSERT INTO compact_memory_guard SELECT NOT EXISTS(SELECT 1 FROM runtime_state WHERE (namespace='MEMORY_PREFERENCE') AND (session_id IS NOT NULL OR state_key IS NOT NULL OR state_code IS NOT NULL OR current_ref IS NOT NULL OR counter_value IS NOT NULL OR provider IS NOT NULL OR credential_sha256 IS NOT NULL OR actor_user_id IS NOT NULL OR request_id IS NOT NULL OR window_started_at IS NOT NULL OR window_ends_at IS NOT NULL));
INSERT INTO compact_memory_guard SELECT NOT EXISTS(SELECT 1 FROM workflow_instance WHERE (kind='MEMORY_MUTATION') AND (chat_action_session_id IS NOT NULL OR confirmation_recorded_at IS NOT NULL OR actor_user_id IS NOT NULL OR parent_workflow_id IS NOT NULL OR resource_revision IS NOT NULL OR requested_tokens IS NOT NULL OR decider_user_id IS NOT NULL OR session_id IS NOT NULL OR run_id IS NOT NULL OR active_slot IS NOT NULL OR claim_token IS NOT NULL OR lease_expires_at IS NOT NULL OR NOT(attempts<=>0) OR effective_date IS NOT NULL OR scheduled_for IS NOT NULL OR error_code IS NOT NULL OR next_attempt_at IS NOT NULL OR expires_at IS NOT NULL OR execution_state IS NOT NULL OR reserved_bytes IS NOT NULL OR exit_verified IS NOT NULL OR execution_deadline IS NOT NULL OR result_version IS NOT NULL OR result_json IS NOT NULL OR result_sha256 IS NOT NULL));
COMMIT;
DROP TEMPORARY TABLE compact_memory_guard;
DROP TEMPORARY TABLE compact_memory_columns;
DROP TEMPORARY TABLE compact_memory_indexes;
