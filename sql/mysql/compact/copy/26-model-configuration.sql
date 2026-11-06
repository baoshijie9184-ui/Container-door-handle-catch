-- Isolated ECS candidate only; source writes must already be fenced by the migration runner.
-- Render __SOURCE_SCHEMA__ and the observed __SOURCE_MODEL_OFFSET__ explicitly.
-- Ciphertexts and revision-associated encryption identities are copied byte-for-byte.
-- Old probe completion times/actors were not stored: keep them unknown, never infer them.
-- Target updated_at records this import, not a source status-change timestamp.
CREATE TEMPORARY TABLE compact_model_guard(ok TINYINT NOT NULL CHECK(ok=1));
START TRANSACTION;
-- BEGIN reviewed fixed-offset conversion guards
INSERT INTO compact_model_guard SELECT IF(REGEXP_LIKE('__SOURCE_MODEL_OFFSET__','^[+-][0-9]{2}:[0-9]{2}$','c') AND CONVERT_TZ('2026-01-01','__SOURCE_MODEL_OFFSET__','+00:00') IS NOT NULL,1,0);
INSERT INTO compact_model_guard SELECT NOT EXISTS(SELECT 1 FROM `__SOURCE_SCHEMA__`.agent_model_configuration s WHERE (s.created_at IS NOT NULL AND (CONVERT_TZ(s.created_at,'__SOURCE_MODEL_OFFSET__','+00:00') IS NULL OR NOT(TIMESTAMPDIFF(MICROSECOND,CONVERT_TZ(s.created_at,'__SOURCE_MODEL_OFFSET__','+00:00'),s.created_at)<=>((IF(LEFT('__SOURCE_MODEL_OFFSET__',1)='-',-1,1)*(CAST(SUBSTRING('__SOURCE_MODEL_OFFSET__',2,2) AS UNSIGNED)*3600+CAST(SUBSTRING('__SOURCE_MODEL_OFFSET__',5,2) AS UNSIGNED)*60))*1000000)))) OR (s.published_at IS NOT NULL AND (CONVERT_TZ(s.published_at,'__SOURCE_MODEL_OFFSET__','+00:00') IS NULL OR NOT(TIMESTAMPDIFF(MICROSECOND,CONVERT_TZ(s.published_at,'__SOURCE_MODEL_OFFSET__','+00:00'),s.published_at)<=>((IF(LEFT('__SOURCE_MODEL_OFFSET__',1)='-',-1,1)*(CAST(SUBSTRING('__SOURCE_MODEL_OFFSET__',2,2) AS UNSIGNED)*3600+CAST(SUBSTRING('__SOURCE_MODEL_OFFSET__',5,2) AS UNSIGNED)*60))*1000000)))));
INSERT INTO compact_model_guard SELECT NOT EXISTS(SELECT 1 FROM `__SOURCE_SCHEMA__`.agent_model_config_command s WHERE (s.created_at IS NOT NULL AND (CONVERT_TZ(s.created_at,'__SOURCE_MODEL_OFFSET__','+00:00') IS NULL OR NOT(TIMESTAMPDIFF(MICROSECOND,CONVERT_TZ(s.created_at,'__SOURCE_MODEL_OFFSET__','+00:00'),s.created_at)<=>((IF(LEFT('__SOURCE_MODEL_OFFSET__',1)='-',-1,1)*(CAST(SUBSTRING('__SOURCE_MODEL_OFFSET__',2,2) AS UNSIGNED)*3600+CAST(SUBSTRING('__SOURCE_MODEL_OFFSET__',5,2) AS UNSIGNED)*60))*1000000)))));
INSERT INTO compact_model_guard SELECT NOT EXISTS(SELECT 1 FROM `__SOURCE_SCHEMA__`.agent_model_json_probe s WHERE (s.created_at IS NOT NULL AND (CONVERT_TZ(s.created_at,'__SOURCE_MODEL_OFFSET__','+00:00') IS NULL OR NOT(TIMESTAMPDIFF(MICROSECOND,CONVERT_TZ(s.created_at,'__SOURCE_MODEL_OFFSET__','+00:00'),s.created_at)<=>((IF(LEFT('__SOURCE_MODEL_OFFSET__',1)='-',-1,1)*(CAST(SUBSTRING('__SOURCE_MODEL_OFFSET__',2,2) AS UNSIGNED)*3600+CAST(SUBSTRING('__SOURCE_MODEL_OFFSET__',5,2) AS UNSIGNED)*60))*1000000)))));
INSERT INTO compact_model_guard SELECT NOT EXISTS(SELECT 1 FROM `__SOURCE_SCHEMA__`.agent_model_revoked_key s WHERE (s.created_at IS NOT NULL AND (CONVERT_TZ(s.created_at,'__SOURCE_MODEL_OFFSET__','+00:00') IS NULL OR NOT(TIMESTAMPDIFF(MICROSECOND,CONVERT_TZ(s.created_at,'__SOURCE_MODEL_OFFSET__','+00:00'),s.created_at)<=>((IF(LEFT('__SOURCE_MODEL_OFFSET__',1)='-',-1,1)*(CAST(SUBSTRING('__SOURCE_MODEL_OFFSET__',2,2) AS UNSIGNED)*3600+CAST(SUBSTRING('__SOURCE_MODEL_OFFSET__',5,2) AS UNSIGNED)*60))*1000000)))));
-- END reviewed fixed-offset conversion guards
SET @compact_model_imported_at=UTC_TIMESTAMP(6);
INSERT INTO compact_model_guard SELECT
 NOT EXISTS(SELECT 1 FROM llm_configuration)
 AND NOT EXISTS(SELECT 1 FROM runtime_state WHERE namespace IN ('MODEL_CONFIG_CONTROL','MODEL_KEY_REVOCATION'))
 AND NOT EXISTS(SELECT 1 FROM workflow_instance WHERE kind IN ('MODEL_CONFIG_COMMAND','MODEL_JSON_PROBE'));
INSERT INTO compact_model_guard SELECT
 (SELECT COUNT(*) FROM `__SOURCE_SCHEMA__`.agent_model_config_control)=1
 AND (SELECT COUNT(*) FROM `__SOURCE_SCHEMA__`.agent_model_config_control WHERE control_id=1)=1;
INSERT INTO compact_model_guard SELECT NOT EXISTS(
 SELECT 1 FROM `__SOURCE_SCHEMA__`.agent_model_config_control c
 WHERE (c.active_revision>=0 AND c.sequence_value>=c.active_revision
   AND c.sequence_value>=(SELECT COALESCE(MAX(revision),0) FROM `__SOURCE_SCHEMA__`.agent_model_configuration)
   AND ((c.active_revision=0 AND NOT EXISTS(SELECT 1 FROM `__SOURCE_SCHEMA__`.agent_model_configuration))
        OR (c.active_revision>0 AND EXISTS(SELECT 1 FROM `__SOURCE_SCHEMA__`.agent_model_configuration m
              WHERE m.revision=c.active_revision AND BINARY m.status=BINARY 'PUBLISHED')))) IS NOT TRUE
);
INSERT INTO compact_model_guard SELECT NOT EXISTS(
 SELECT 1 FROM `__SOURCE_SCHEMA__`.agent_model_configuration m
 WHERE (m.revision>0 AND m.base_revision>=0 AND BINARY m.status IN ('DRAFT','VALIDATED','PUBLISHED','RETIRED')
    AND JSON_VALID(m.document_json) AND m.sealed_snapshot IS NOT NULL AND m.memory_envelope IS NOT NULL
    AND m.request_id IS NOT NULL AND CHAR_LENGTH(m.request_id)>0
    AND m.request_sha256 REGEXP '^[a-f0-9]{64}$'
    AND BINARY m.memory_state IN ('PENDING','ENVIRONMENT','APPLIED')
    AND CONVERT_TZ(m.created_at,'__SOURCE_MODEL_OFFSET__','+00:00') IS NOT NULL
    AND (m.published_at IS NULL OR CONVERT_TZ(m.published_at,'__SOURCE_MODEL_OFFSET__','+00:00') IS NOT NULL)
    AND (m.creator_user_id IS NULL OR m.creator_user_id>0)
    AND (m.base_revision=0 OR EXISTS(SELECT 1 FROM `__SOURCE_SCHEMA__`.agent_model_configuration b WHERE b.revision=m.base_revision))) IS NOT TRUE
);
INSERT INTO compact_model_guard SELECT
 (SELECT COUNT(*) FROM `__SOURCE_SCHEMA__`.agent_model_configuration WHERE status='PUBLISHED')=
 (SELECT CASE WHEN active_revision=0 THEN 0 ELSE 1 END FROM `__SOURCE_SCHEMA__`.agent_model_config_control WHERE control_id=1);
INSERT INTO compact_model_guard SELECT NOT EXISTS(
 SELECT 1 FROM `__SOURCE_SCHEMA__`.agent_model_revoked_key r
 WHERE (BINARY r.provider IN ('dashscope','deepseek','openai') AND r.key_sha256 REGEXP '^[a-f0-9]{64}$'
    AND r.actor_user_id>0 AND r.request_id IS NOT NULL AND CHAR_LENGTH(r.request_id)>0
    AND r.memory_propagated IN (0,1)
    AND CONVERT_TZ(r.created_at,'__SOURCE_MODEL_OFFSET__','+00:00') IS NOT NULL) IS NOT TRUE
);
INSERT INTO compact_model_guard SELECT NOT EXISTS(
 SELECT 1 FROM `__SOURCE_SCHEMA__`.agent_model_config_command c
 LEFT JOIN `__SOURCE_SCHEMA__`.agent_model_configuration m ON m.revision=c.revision
 WHERE (m.revision IS NOT NULL AND c.actor_user_id>0 AND CHAR_LENGTH(c.request_id)>0
    AND BINARY c.action IN ('VALIDATE','PUBLISH','REVOKE_KEY') AND CHAR_LENGTH(c.target)>0
    AND CONVERT_TZ(c.created_at,'__SOURCE_MODEL_OFFSET__','+00:00') IS NOT NULL) IS NOT TRUE
);
INSERT INTO compact_model_guard SELECT NOT EXISTS(
 SELECT 1 FROM `__SOURCE_SCHEMA__`.agent_model_json_probe p
 LEFT JOIN `__SOURCE_SCHEMA__`.agent_model_configuration m ON m.revision=p.revision
 WHERE (m.revision IS NOT NULL AND m.creator_user_id IS NOT NULL AND m.creator_user_id>0
    AND BINARY p.status IN ('STARTED','PASSED','FAILED') AND CHAR_LENGTH(p.model_id) BETWEEN 1 AND 160
    AND CHAR_LENGTH(p.request_id)>0
    AND CONVERT_TZ(p.created_at,'__SOURCE_MODEL_OFFSET__','+00:00') IS NOT NULL) IS NOT TRUE
);

INSERT INTO llm_configuration(revision,base_revision,status,document_json,sealed_snapshot,memory_envelope,
 creator_user_id,request_id,request_sha256,memory_state,created_at,published_at)
SELECT revision,base_revision,status,document_json,sealed_snapshot,memory_envelope,creator_user_id,
 request_id,request_sha256,memory_state,
 CONVERT_TZ(created_at,'__SOURCE_MODEL_OFFSET__','+00:00'),
 CONVERT_TZ(published_at,'__SOURCE_MODEL_OFFSET__','+00:00')
FROM `__SOURCE_SCHEMA__`.agent_model_configuration;

-- The original singleton has no creation timestamp; NULL preserves that absence.
INSERT INTO runtime_state(namespace,owner_id,scope_key,revision,state_code,current_ref,counter_value,created_at,updated_at)
SELECT 'MODEL_CONFIG_CONTROL',0,'GLOBAL',0,'READY',CAST(active_revision AS CHAR),sequence_value,NULL,@compact_model_imported_at
FROM `__SOURCE_SCHEMA__`.agent_model_config_control WHERE control_id=1;
INSERT INTO runtime_state(namespace,owner_id,scope_key,revision,state_code,counter_value,
 provider,credential_sha256,actor_user_id,request_id,created_at,updated_at)
SELECT 'MODEL_KEY_REVOCATION',0,CONCAT(provider,':',key_sha256),1,'REVOKED',memory_propagated,
 provider,key_sha256,actor_user_id,request_id,
 CONVERT_TZ(created_at,'__SOURCE_MODEL_OFFSET__','+00:00'),@compact_model_imported_at
FROM `__SOURCE_SCHEMA__`.agent_model_revoked_key;

INSERT INTO workflow_instance(workflow_id,kind,idempotency_scope,request_id,request_sha256,
 owner_user_id,actor_user_id,resource_type,resource_id,resource_revision,status,payload_version,payload_json,
 created_at,updated_at,finished_at,legacy_source,legacy_key)
SELECT UUID(),'MODEL_CONFIG_COMMAND',CONCAT('OWNER:',actor_user_id),request_id,
 SHA2(CONCAT(OCTET_LENGTH(action),':',action,OCTET_LENGTH(target),':',target),256),
 actor_user_id,actor_user_id,'LLM_CONFIGURATION',CAST(revision AS CHAR),revision,'COMPLETED',1,
 JSON_OBJECT('action',action,'target',target),
 CONVERT_TZ(created_at,'__SOURCE_MODEL_OFFSET__','+00:00'),@compact_model_imported_at,
 CONVERT_TZ(created_at,'__SOURCE_MODEL_OFFSET__','+00:00'),
 'agent_model_config_command',CONCAT(actor_user_id,':',request_id)
FROM `__SOURCE_SCHEMA__`.agent_model_config_command;

INSERT INTO workflow_instance(workflow_id,kind,idempotency_scope,request_id,request_sha256,
 owner_user_id,actor_user_id,resource_type,resource_id,resource_revision,status,payload_version,payload_json,
 created_at,updated_at,finished_at,legacy_source,legacy_key)
SELECT UUID(),'MODEL_JSON_PROBE',CONCAT('MODEL_CONFIG:',p.revision),p.request_id,
 SHA2(CONCAT(OCTET_LENGTH(CAST(p.revision AS CHAR)),':',p.revision,OCTET_LENGTH(p.model_id),':',p.model_id),256),
 m.creator_user_id,NULL,'LLM_CONFIGURATION',CAST(p.revision AS CHAR),p.revision,p.status,1,
 JSON_OBJECT('modelId',p.model_id),
 CONVERT_TZ(p.created_at,'__SOURCE_MODEL_OFFSET__','+00:00'),@compact_model_imported_at,NULL,
 'agent_model_json_probe',CONCAT(p.revision,':',p.request_id)
FROM `__SOURCE_SCHEMA__`.agent_model_json_probe p
JOIN `__SOURCE_SCHEMA__`.agent_model_configuration m ON m.revision=p.revision;

INSERT INTO compact_model_guard SELECT
 (SELECT COUNT(*) FROM llm_configuration)=(SELECT COUNT(*) FROM `__SOURCE_SCHEMA__`.agent_model_configuration)
 AND (SELECT COUNT(*) FROM runtime_state WHERE namespace='MODEL_CONFIG_CONTROL')=1
 AND (SELECT COUNT(*) FROM runtime_state WHERE namespace='MODEL_KEY_REVOCATION')=(SELECT COUNT(*) FROM `__SOURCE_SCHEMA__`.agent_model_revoked_key)
 AND (SELECT COUNT(*) FROM workflow_instance WHERE kind='MODEL_CONFIG_COMMAND')=(SELECT COUNT(*) FROM `__SOURCE_SCHEMA__`.agent_model_config_command)
 AND (SELECT COUNT(*) FROM workflow_instance WHERE kind='MODEL_JSON_PROBE')=(SELECT COUNT(*) FROM `__SOURCE_SCHEMA__`.agent_model_json_probe);
INSERT INTO compact_model_guard SELECT NOT EXISTS(
 SELECT 1 FROM `__SOURCE_SCHEMA__`.agent_model_configuration s LEFT JOIN llm_configuration t ON t.revision=s.revision
 WHERE t.revision IS NULL OR NOT(t.base_revision<=>s.base_revision) OR NOT(BINARY t.status<=>BINARY s.status)
  OR NOT(BINARY CAST(t.document_json AS CHAR)<=>BINARY CAST(s.document_json AS CHAR))
  OR NOT(BINARY t.sealed_snapshot<=>BINARY s.sealed_snapshot) OR NOT(BINARY t.memory_envelope<=>BINARY s.memory_envelope)
  OR NOT(t.creator_user_id<=>s.creator_user_id) OR NOT(BINARY t.request_id<=>BINARY s.request_id)
  OR NOT(BINARY t.request_sha256<=>BINARY s.request_sha256) OR NOT(BINARY t.memory_state<=>BINARY s.memory_state)
  OR NOT(t.created_at<=>CONVERT_TZ(s.created_at,'__SOURCE_MODEL_OFFSET__','+00:00'))
  OR NOT(t.published_at<=>CONVERT_TZ(s.published_at,'__SOURCE_MODEL_OFFSET__','+00:00'))
);
INSERT INTO compact_model_guard SELECT NOT EXISTS(
 SELECT 1 FROM `__SOURCE_SCHEMA__`.agent_model_config_control s LEFT JOIN runtime_state t
 ON t.namespace='MODEL_CONFIG_CONTROL' AND t.owner_id=0 AND t.scope_key='GLOBAL'
 WHERE t.namespace IS NULL OR NOT(BINARY t.current_ref<=>BINARY CAST(s.active_revision AS CHAR))
  OR NOT(t.counter_value<=>s.sequence_value) OR t.created_at IS NOT NULL
  OR NOT(BINARY t.scope_key<=>BINARY 'GLOBAL') OR NOT(t.revision<=>0)
);
INSERT INTO compact_model_guard SELECT NOT EXISTS(
 SELECT 1 FROM `__SOURCE_SCHEMA__`.agent_model_revoked_key s LEFT JOIN runtime_state t
 ON t.namespace='MODEL_KEY_REVOCATION' AND t.owner_id=0 AND t.scope_key=CONCAT(s.provider,':',s.key_sha256)
 WHERE t.namespace IS NULL OR NOT(BINARY t.provider<=>BINARY s.provider)
  OR NOT(BINARY t.scope_key<=>BINARY CONCAT(s.provider,':',s.key_sha256))
  OR NOT(BINARY t.credential_sha256<=>BINARY s.key_sha256) OR NOT(t.actor_user_id<=>s.actor_user_id)
  OR NOT(BINARY t.request_id<=>BINARY s.request_id) OR NOT(t.counter_value<=>s.memory_propagated)
  OR NOT(t.created_at<=>CONVERT_TZ(s.created_at,'__SOURCE_MODEL_OFFSET__','+00:00'))
);
INSERT INTO compact_model_guard SELECT NOT EXISTS(
 SELECT 1 FROM `__SOURCE_SCHEMA__`.agent_model_config_command s LEFT JOIN workflow_instance t
 ON t.kind='MODEL_CONFIG_COMMAND' AND t.idempotency_scope=CONCAT('OWNER:',s.actor_user_id) AND t.request_id=s.request_id
 WHERE t.id IS NULL OR NOT(t.owner_user_id<=>s.actor_user_id) OR NOT(t.actor_user_id<=>s.actor_user_id)
  OR NOT(BINARY t.request_id<=>BINARY s.request_id)
  OR NOT(BINARY t.idempotency_scope<=>BINARY CONCAT('OWNER:',s.actor_user_id))
  OR NOT(BINARY t.resource_id<=>BINARY CAST(s.revision AS CHAR))
  OR NOT(BINARY t.legacy_source<=>BINARY 'agent_model_config_command')
  OR NOT(BINARY t.legacy_key<=>BINARY CONCAT(s.actor_user_id,':',s.request_id))
  OR NOT(t.resource_revision<=>s.revision)
  OR NOT(BINARY JSON_UNQUOTE(JSON_EXTRACT(t.payload_json,'$.action'))<=>BINARY s.action)
  OR NOT(BINARY JSON_UNQUOTE(JSON_EXTRACT(t.payload_json,'$.target'))<=>BINARY s.target)
  OR NOT(BINARY t.request_sha256<=>BINARY SHA2(CONCAT(OCTET_LENGTH(s.action),':',s.action,OCTET_LENGTH(s.target),':',s.target),256))
  OR NOT(t.created_at<=>CONVERT_TZ(s.created_at,'__SOURCE_MODEL_OFFSET__','+00:00'))
  OR NOT(t.finished_at<=>CONVERT_TZ(s.created_at,'__SOURCE_MODEL_OFFSET__','+00:00'))
);
INSERT INTO compact_model_guard SELECT NOT EXISTS(
 SELECT 1 FROM `__SOURCE_SCHEMA__`.agent_model_json_probe s
 JOIN `__SOURCE_SCHEMA__`.agent_model_configuration m ON m.revision=s.revision
 LEFT JOIN workflow_instance t ON t.kind='MODEL_JSON_PROBE' AND t.idempotency_scope=CONCAT('MODEL_CONFIG:',s.revision) AND t.request_id=s.request_id
 WHERE t.id IS NULL OR NOT(t.owner_user_id<=>m.creator_user_id) OR t.actor_user_id IS NOT NULL
  OR NOT(BINARY t.request_id<=>BINARY s.request_id)
  OR NOT(BINARY t.idempotency_scope<=>BINARY CONCAT('MODEL_CONFIG:',s.revision))
  OR NOT(BINARY t.resource_id<=>BINARY CAST(s.revision AS CHAR))
  OR NOT(BINARY t.legacy_source<=>BINARY 'agent_model_json_probe')
  OR NOT(BINARY t.legacy_key<=>BINARY CONCAT(s.revision,':',s.request_id))
  OR NOT(t.resource_revision<=>s.revision) OR NOT(BINARY t.model_probe_id<=>BINARY s.model_id)
  OR NOT(BINARY t.status<=>BINARY s.status)
  OR NOT(BINARY t.request_sha256<=>BINARY SHA2(CONCAT(OCTET_LENGTH(CAST(s.revision AS CHAR)),':',s.revision,OCTET_LENGTH(s.model_id),':',s.model_id),256))
  OR NOT(t.created_at<=>CONVERT_TZ(s.created_at,'__SOURCE_MODEL_OFFSET__','+00:00'))
  OR t.finished_at IS NOT NULL
);
COMMIT;
DROP TEMPORARY TABLE compact_model_guard;
