-- USE the empty compact target. Render only validated identifiers and evidence-backed UTC offsets.
-- __SOURCE_INBOX_OFFSET__ describes source DATETIME wall time, not the runner session time zone.
-- Stop all source writers first. Abort on the first error and ROLLBACK on this same connection.
CREATE TEMPORARY TABLE compact_inbox_guard(valid INT NOT NULL CHECK(valid=1));
START TRANSACTION;
-- BEGIN reviewed fixed-offset conversion guards
INSERT INTO compact_inbox_guard SELECT IF(REGEXP_LIKE('__SOURCE_INBOX_OFFSET__','^[+-][0-9]{2}:[0-9]{2}$','c') AND CONVERT_TZ('2026-01-01','__SOURCE_INBOX_OFFSET__','+00:00') IS NOT NULL,1,0);
INSERT INTO compact_inbox_guard SELECT NOT EXISTS(SELECT 1 FROM `__SOURCE_SCHEMA__`.agent_conversation_input s WHERE (s.created_at IS NOT NULL AND (CONVERT_TZ(s.created_at,'__SOURCE_INBOX_OFFSET__','+00:00') IS NULL OR NOT(TIMESTAMPDIFF(MICROSECOND,CONVERT_TZ(s.created_at,'__SOURCE_INBOX_OFFSET__','+00:00'),s.created_at)<=>((IF(LEFT('__SOURCE_INBOX_OFFSET__',1)='-',-1,1)*(CAST(SUBSTRING('__SOURCE_INBOX_OFFSET__',2,2) AS SIGNED)*3600+CAST(SUBSTRING('__SOURCE_INBOX_OFFSET__',5,2) AS SIGNED)*60))*1000000)))) OR (s.updated_at IS NOT NULL AND (CONVERT_TZ(s.updated_at,'__SOURCE_INBOX_OFFSET__','+00:00') IS NULL OR NOT(TIMESTAMPDIFF(MICROSECOND,CONVERT_TZ(s.updated_at,'__SOURCE_INBOX_OFFSET__','+00:00'),s.updated_at)<=>((IF(LEFT('__SOURCE_INBOX_OFFSET__',1)='-',-1,1)*(CAST(SUBSTRING('__SOURCE_INBOX_OFFSET__',2,2) AS SIGNED)*3600+CAST(SUBSTRING('__SOURCE_INBOX_OFFSET__',5,2) AS SIGNED)*60))*1000000)))) OR (s.expires_at IS NOT NULL AND (CONVERT_TZ(s.expires_at,'__SOURCE_INBOX_OFFSET__','+00:00') IS NULL OR NOT(TIMESTAMPDIFF(MICROSECOND,CONVERT_TZ(s.expires_at,'__SOURCE_INBOX_OFFSET__','+00:00'),s.expires_at)<=>((IF(LEFT('__SOURCE_INBOX_OFFSET__',1)='-',-1,1)*(CAST(SUBSTRING('__SOURCE_INBOX_OFFSET__',2,2) AS SIGNED)*3600+CAST(SUBSTRING('__SOURCE_INBOX_OFFSET__',5,2) AS SIGNED)*60))*1000000)))));
INSERT INTO compact_inbox_guard SELECT NOT EXISTS(SELECT 1 FROM `__SOURCE_SCHEMA__`.agent_conversation_input_audit s WHERE (s.created_at IS NOT NULL AND (CONVERT_TZ(s.created_at,'__SOURCE_INBOX_OFFSET__','+00:00') IS NULL OR NOT(TIMESTAMPDIFF(MICROSECOND,CONVERT_TZ(s.created_at,'__SOURCE_INBOX_OFFSET__','+00:00'),s.created_at)<=>((IF(LEFT('__SOURCE_INBOX_OFFSET__',1)='-',-1,1)*(CAST(SUBSTRING('__SOURCE_INBOX_OFFSET__',2,2) AS SIGNED)*3600+CAST(SUBSTRING('__SOURCE_INBOX_OFFSET__',5,2) AS SIGNED)*60))*1000000)))));
-- END reviewed fixed-offset conversion guards
INSERT INTO compact_inbox_guard SELECT IF(COUNT(*)=0,1,0) FROM workflow_instance WHERE kind='CONVERSATION_INPUT';
INSERT INTO compact_inbox_guard SELECT IF(COUNT(*)=0,1,0) FROM audit_event WHERE kind='CONVERSATION_INPUT';
INSERT INTO compact_inbox_guard SELECT IF(CONVERT_TZ('2026-01-01 00:00:00','__SOURCE_INBOX_OFFSET__','+00:00') IS NOT NULL,1,0);
INSERT INTO compact_inbox_guard SELECT IF(COUNT(*)=0,1,0) FROM `__SOURCE_SCHEMA__`.agent_conversation_input_owner WHERE user_id<=0;
INSERT INTO compact_inbox_guard SELECT IF(COUNT(*)=0,1,0) FROM `__SOURCE_SCHEMA__`.agent_conversation_input i
 WHERE i.user_id<=0 OR i.revision<0 OR i.username='' OR i.session_id=''
 OR i.mode NOT IN ('NEXT_TURN','NEXT_STEP') OR i.requested_mode NOT IN ('NEXT_TURN','NEXT_STEP') OR i.entry_point NOT IN ('CHAT','AGUI')
 OR i.status NOT IN ('QUEUED','STARTED','APPLIED','COMPLETED','CANCELLED','FAILED','EXPIRED')
 OR i.content_sha256 NOT REGEXP '^[a-f0-9]{64}$'
 OR OCTET_LENGTH(CONVERT(i.content USING utf16))/2>IF(i.mode='NEXT_STEP',4000,8000)
 OR (i.status='QUEUED' AND (TRIM(i.content)='' OR BINARY i.content_sha256<>BINARY SHA2(CONVERT(i.content USING utf8mb4),256)))
 OR (i.status='STARTED' AND (i.active_slot IS NULL OR i.active_slot<>1))
 OR (i.status<>'STARTED' AND i.active_slot IS NOT NULL)
 OR CONVERT_TZ(i.created_at,'__SOURCE_INBOX_OFFSET__','+00:00') IS NULL
 OR CONVERT_TZ(i.updated_at,'__SOURCE_INBOX_OFFSET__','+00:00') IS NULL
 OR CONVERT_TZ(i.expires_at,'__SOURCE_INBOX_OFFSET__','+00:00') IS NULL;
-- Legacy edits replace content_sha256. The immutable enqueue audit is the evidence for the original request.
INSERT INTO compact_inbox_guard SELECT IF(COUNT(*)=0,1,0) FROM `__SOURCE_SCHEMA__`.agent_conversation_input i
 WHERE (SELECT COUNT(*) FROM `__SOURCE_SCHEMA__`.agent_conversation_input_audit a WHERE BINARY a.input_id=BINARY i.input_id AND a.user_id=i.user_id AND a.action='ENQUEUED')<>1;
INSERT INTO compact_inbox_guard SELECT IF(COUNT(*)=0,1,0)
 FROM `__SOURCE_SCHEMA__`.agent_conversation_input_audit a LEFT JOIN `__SOURCE_SCHEMA__`.agent_conversation_input i ON BINARY i.input_id=BINARY a.input_id
 WHERE i.id IS NULL OR a.user_id<>i.user_id OR a.revision<0 OR a.content_sha256 NOT REGEXP '^[a-f0-9]{64}$'
 OR a.action NOT IN ('ENQUEUED','EDITED','CANCELLED','PROMOTED_NEXT_STEP','APPLIED_AT_BOUNDARY','FALLBACK_NEXT_TURN','STARTED','COMPLETED','ACCOUNT_OR_SESSION_UNAVAILABLE','EXECUTOR_UNAVAILABLE','EXECUTION_FAILED_NO_AUTO_RETRY','EXPIRED')
 OR CONVERT_TZ(a.created_at,'__SOURCE_INBOX_OFFSET__','+00:00') IS NULL;

INSERT INTO workflow_instance(workflow_id,kind,idempotency_scope,request_id,request_sha256,owner_user_id,actor_user_id,
 resource_type,resource_id,session_id,run_id,status,revision,fence,active_slot,claim_token,lease_expires_at,expires_at,
 payload_version,payload_json,created_at,updated_at,finished_at,legacy_source,legacy_key)
 SELECT i.input_id,'CONVERSATION_INPUT','GLOBAL',i.input_id,
 SHA2(CONCAT(i.user_id,'|',OCTET_LENGTH(CONVERT(i.session_id USING utf16))/2,':',i.session_id,'|',i.requested_mode,'|',i.entry_point,'|',a.content_sha256),256),
 i.user_id,i.user_id,'SESSION',i.session_id,i.session_id,i.target_run_id,i.status,i.revision,IF(i.status='STARTED',1,0),i.active_slot,
 IF(i.status='STARTED',SHA2(CONCAT('legacy-inbox-claim:',i.input_id),256),NULL),
 IF(i.status='STARTED',CONVERT_TZ(i.expires_at,'__SOURCE_INBOX_OFFSET__','+00:00'),NULL),CONVERT_TZ(i.expires_at,'__SOURCE_INBOX_OFFSET__','+00:00'),1,
 JSON_OBJECT('username',i.username,'mode',i.mode,'requestedMode',i.requested_mode,'entryPoint',i.entry_point,'content',i.content,'contentSha256',i.content_sha256),
 CONVERT_TZ(i.created_at,'__SOURCE_INBOX_OFFSET__','+00:00'),CONVERT_TZ(i.updated_at,'__SOURCE_INBOX_OFFSET__','+00:00'),
 IF(i.status IN ('QUEUED','STARTED'),NULL,CONVERT_TZ(i.updated_at,'__SOURCE_INBOX_OFFSET__','+00:00')),'agent_conversation_input',CAST(i.id AS CHAR)
 FROM `__SOURCE_SCHEMA__`.agent_conversation_input i JOIN `__SOURCE_SCHEMA__`.agent_conversation_input_audit a ON BINARY a.input_id=BINARY i.input_id AND a.user_id=i.user_id AND a.action='ENQUEUED'
 ORDER BY i.id;
-- Imported STARTED rows retain their state/deadline; a technical migration fence prevents replay.
-- Their old process is stopped. They expire normally; migration never invents completion or failure.
INSERT INTO audit_event(event_id,kind,owner_user_id,actor_user_id,resource_type,resource_id,session_id,request_id,action,revision,content_sha256,occurred_at,payload_version,payload_json,legacy_source,legacy_key)
 SELECT CONCAT('legacy-inbox-',a.id),'CONVERSATION_INPUT',a.user_id,a.user_id,'CONVERSATION_INPUT',a.input_id,i.session_id,a.input_id,a.action,a.revision,a.content_sha256,
 CONVERT_TZ(a.created_at,'__SOURCE_INBOX_OFFSET__','+00:00'),1,
 JSON_OBJECT('status',CASE a.action WHEN 'CANCELLED' THEN 'CANCELLED' WHEN 'APPLIED_AT_BOUNDARY' THEN 'APPLIED' WHEN 'STARTED' THEN 'STARTED' WHEN 'COMPLETED' THEN 'COMPLETED' WHEN 'EXPIRED' THEN 'EXPIRED' WHEN 'ACCOUNT_OR_SESSION_UNAVAILABLE' THEN 'FAILED' WHEN 'EXECUTOR_UNAVAILABLE' THEN 'FAILED' WHEN 'EXECUTION_FAILED_NO_AUTO_RETRY' THEN 'FAILED' ELSE 'QUEUED' END),
 'agent_conversation_input_audit',CAST(a.id AS CHAR)
 FROM `__SOURCE_SCHEMA__`.agent_conversation_input_audit a JOIN `__SOURCE_SCHEMA__`.agent_conversation_input i ON BINARY i.input_id=BINARY a.input_id ORDER BY a.id;
INSERT INTO runtime_state(namespace,owner_id,scope_key,revision,created_at)
 SELECT 'CONVERSATION_INPUT',user_id,'',0,NULL FROM `__SOURCE_SCHEMA__`.agent_conversation_input_owner
 ON DUPLICATE KEY UPDATE namespace=runtime_state.namespace;

INSERT INTO compact_inbox_guard SELECT IF(
 (SELECT COUNT(*) FROM workflow_instance WHERE kind='CONVERSATION_INPUT')=(SELECT COUNT(*) FROM `__SOURCE_SCHEMA__`.agent_conversation_input)
 AND (SELECT COUNT(*) FROM audit_event WHERE kind='CONVERSATION_INPUT')=(SELECT COUNT(*) FROM `__SOURCE_SCHEMA__`.agent_conversation_input_audit),1,0);
INSERT INTO compact_inbox_guard SELECT IF(COUNT(*)=0,1,0)
 FROM `__SOURCE_SCHEMA__`.agent_conversation_input i LEFT JOIN workflow_instance w ON w.kind='CONVERSATION_INPUT' AND BINARY w.workflow_id=BINARY i.input_id
 WHERE w.id IS NULL OR w.owner_user_id<>i.user_id OR BINARY w.session_id<>BINARY i.session_id OR w.status<>i.status OR w.revision<>i.revision
 OR NOT (w.run_id<=>i.target_run_id) OR NOT (w.active_slot<=>i.active_slot)
 OR NOT (BINARY w.legacy_key<=>BINARY CAST(i.id AS CHAR)) OR BINARY w.request_id<>BINARY i.input_id OR w.idempotency_scope<>'GLOBAL'
 OR NOT (BINARY JSON_UNQUOTE(JSON_EXTRACT(w.payload_json,'$.username'))<=>BINARY i.username)
 OR NOT (BINARY JSON_UNQUOTE(JSON_EXTRACT(w.payload_json,'$.mode'))<=>BINARY i.mode)
 OR NOT (BINARY JSON_UNQUOTE(JSON_EXTRACT(w.payload_json,'$.requestedMode'))<=>BINARY i.requested_mode)
 OR NOT (BINARY JSON_UNQUOTE(JSON_EXTRACT(w.payload_json,'$.entryPoint'))<=>BINARY i.entry_point)
 OR NOT (BINARY JSON_UNQUOTE(JSON_EXTRACT(w.payload_json,'$.content'))<=>BINARY i.content)
 OR NOT (BINARY JSON_UNQUOTE(JSON_EXTRACT(w.payload_json,'$.contentSha256'))<=>BINARY i.content_sha256)
 OR w.expires_at<>CONVERT_TZ(i.expires_at,'__SOURCE_INBOX_OFFSET__','+00:00')
 OR w.created_at<>CONVERT_TZ(i.created_at,'__SOURCE_INBOX_OFFSET__','+00:00') OR w.updated_at<>CONVERT_TZ(i.updated_at,'__SOURCE_INBOX_OFFSET__','+00:00');
INSERT INTO compact_inbox_guard SELECT IF(COUNT(*)=0,1,0)
 FROM `__SOURCE_SCHEMA__`.agent_conversation_input i JOIN `__SOURCE_SCHEMA__`.agent_conversation_input_audit a ON BINARY a.input_id=BINARY i.input_id AND a.user_id=i.user_id AND a.action='ENQUEUED'
 JOIN workflow_instance w ON w.kind='CONVERSATION_INPUT' AND BINARY w.workflow_id=BINARY i.input_id
 WHERE BINARY w.request_sha256<>BINARY SHA2(CONCAT(i.user_id,'|',OCTET_LENGTH(CONVERT(i.session_id USING utf16))/2,':',i.session_id,'|',i.requested_mode,'|',i.entry_point,'|',a.content_sha256),256);
INSERT INTO compact_inbox_guard SELECT IF(COUNT(*)=0,1,0)
 FROM `__SOURCE_SCHEMA__`.agent_conversation_input_audit a LEFT JOIN audit_event e ON e.legacy_source='agent_conversation_input_audit' AND e.legacy_key=CAST(a.id AS CHAR)
 WHERE e.id IS NULL OR NOT (BINARY e.resource_id<=>BINARY a.input_id) OR NOT (e.owner_user_id<=>a.user_id) OR BINARY e.action<>BINARY a.action OR NOT (e.revision<=>a.revision)
 OR NOT (BINARY e.content_sha256<=>BINARY a.content_sha256) OR e.occurred_at<>CONVERT_TZ(a.created_at,'__SOURCE_INBOX_OFFSET__','+00:00');
COMMIT;
DROP TEMPORARY TABLE compact_inbox_guard;
