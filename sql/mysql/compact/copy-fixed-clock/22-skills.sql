-- Run only on the isolated EMPTY ECS target with source writers stopped.
-- Render __SOURCE_SCHEMA__ as a validated identifier and __SOURCE_SKILL_OFFSET__
-- from the observed source DATETIME convention, never the migration host timezone.
-- The runner must stop at the first error and ROLLBACK on the same connection.
-- Old UPLOAD packages remain evidence archives; this does not re-enable uploads.
CREATE TEMPORARY TABLE compact_skill_guard(ok TINYINT NOT NULL CHECK(ok=1));
START TRANSACTION;
-- BEGIN reviewed fixed-offset conversion guards
INSERT INTO compact_skill_guard SELECT IF(REGEXP_LIKE('__SOURCE_SKILL_OFFSET__','^[+-][0-9]{2}:[0-9]{2}$','c') AND CONVERT_TZ('2026-01-01','__SOURCE_SKILL_OFFSET__','+00:00') IS NOT NULL,1,0);
INSERT INTO compact_skill_guard SELECT NOT EXISTS(SELECT 1 FROM `__SOURCE_SCHEMA__`.agent_learned_skill s WHERE (s.created_at IS NOT NULL AND (CONVERT_TZ(s.created_at,'__SOURCE_SKILL_OFFSET__','+00:00') IS NULL OR NOT(TIMESTAMPDIFF(MICROSECOND,CONVERT_TZ(s.created_at,'__SOURCE_SKILL_OFFSET__','+00:00'),s.created_at)<=>((IF(LEFT('__SOURCE_SKILL_OFFSET__',1)='-',-1,1)*(CAST(SUBSTRING('__SOURCE_SKILL_OFFSET__',2,2) AS UNSIGNED)*3600+CAST(SUBSTRING('__SOURCE_SKILL_OFFSET__',5,2) AS UNSIGNED)*60))*1000000)))) OR (s.updated_at IS NOT NULL AND (CONVERT_TZ(s.updated_at,'__SOURCE_SKILL_OFFSET__','+00:00') IS NULL OR NOT(TIMESTAMPDIFF(MICROSECOND,CONVERT_TZ(s.updated_at,'__SOURCE_SKILL_OFFSET__','+00:00'),s.updated_at)<=>((IF(LEFT('__SOURCE_SKILL_OFFSET__',1)='-',-1,1)*(CAST(SUBSTRING('__SOURCE_SKILL_OFFSET__',2,2) AS UNSIGNED)*3600+CAST(SUBSTRING('__SOURCE_SKILL_OFFSET__',5,2) AS UNSIGNED)*60))*1000000)))) OR (s.activated_at IS NOT NULL AND (CONVERT_TZ(s.activated_at,'__SOURCE_SKILL_OFFSET__','+00:00') IS NULL OR NOT(TIMESTAMPDIFF(MICROSECOND,CONVERT_TZ(s.activated_at,'__SOURCE_SKILL_OFFSET__','+00:00'),s.activated_at)<=>((IF(LEFT('__SOURCE_SKILL_OFFSET__',1)='-',-1,1)*(CAST(SUBSTRING('__SOURCE_SKILL_OFFSET__',2,2) AS UNSIGNED)*3600+CAST(SUBSTRING('__SOURCE_SKILL_OFFSET__',5,2) AS UNSIGNED)*60))*1000000)))) OR (s.last_used_at IS NOT NULL AND (CONVERT_TZ(s.last_used_at,'__SOURCE_SKILL_OFFSET__','+00:00') IS NULL OR NOT(TIMESTAMPDIFF(MICROSECOND,CONVERT_TZ(s.last_used_at,'__SOURCE_SKILL_OFFSET__','+00:00'),s.last_used_at)<=>((IF(LEFT('__SOURCE_SKILL_OFFSET__',1)='-',-1,1)*(CAST(SUBSTRING('__SOURCE_SKILL_OFFSET__',2,2) AS UNSIGNED)*3600+CAST(SUBSTRING('__SOURCE_SKILL_OFFSET__',5,2) AS UNSIGNED)*60))*1000000)))));
INSERT INTO compact_skill_guard SELECT NOT EXISTS(SELECT 1 FROM `__SOURCE_SCHEMA__`.agent_skill_version s WHERE (s.created_at IS NOT NULL AND (CONVERT_TZ(s.created_at,'__SOURCE_SKILL_OFFSET__','+00:00') IS NULL OR NOT(TIMESTAMPDIFF(MICROSECOND,CONVERT_TZ(s.created_at,'__SOURCE_SKILL_OFFSET__','+00:00'),s.created_at)<=>((IF(LEFT('__SOURCE_SKILL_OFFSET__',1)='-',-1,1)*(CAST(SUBSTRING('__SOURCE_SKILL_OFFSET__',2,2) AS UNSIGNED)*3600+CAST(SUBSTRING('__SOURCE_SKILL_OFFSET__',5,2) AS UNSIGNED)*60))*1000000)))) OR (s.submitted_at IS NOT NULL AND (CONVERT_TZ(s.submitted_at,'__SOURCE_SKILL_OFFSET__','+00:00') IS NULL OR NOT(TIMESTAMPDIFF(MICROSECOND,CONVERT_TZ(s.submitted_at,'__SOURCE_SKILL_OFFSET__','+00:00'),s.submitted_at)<=>((IF(LEFT('__SOURCE_SKILL_OFFSET__',1)='-',-1,1)*(CAST(SUBSTRING('__SOURCE_SKILL_OFFSET__',2,2) AS UNSIGNED)*3600+CAST(SUBSTRING('__SOURCE_SKILL_OFFSET__',5,2) AS UNSIGNED)*60))*1000000)))) OR (s.reviewed_at IS NOT NULL AND (CONVERT_TZ(s.reviewed_at,'__SOURCE_SKILL_OFFSET__','+00:00') IS NULL OR NOT(TIMESTAMPDIFF(MICROSECOND,CONVERT_TZ(s.reviewed_at,'__SOURCE_SKILL_OFFSET__','+00:00'),s.reviewed_at)<=>((IF(LEFT('__SOURCE_SKILL_OFFSET__',1)='-',-1,1)*(CAST(SUBSTRING('__SOURCE_SKILL_OFFSET__',2,2) AS UNSIGNED)*3600+CAST(SUBSTRING('__SOURCE_SKILL_OFFSET__',5,2) AS UNSIGNED)*60))*1000000)))));
INSERT INTO compact_skill_guard SELECT NOT EXISTS(SELECT 1 FROM `__SOURCE_SCHEMA__`.agent_skill_eval s WHERE (s.created_at IS NOT NULL AND (CONVERT_TZ(s.created_at,'__SOURCE_SKILL_OFFSET__','+00:00') IS NULL OR NOT(TIMESTAMPDIFF(MICROSECOND,CONVERT_TZ(s.created_at,'__SOURCE_SKILL_OFFSET__','+00:00'),s.created_at)<=>((IF(LEFT('__SOURCE_SKILL_OFFSET__',1)='-',-1,1)*(CAST(SUBSTRING('__SOURCE_SKILL_OFFSET__',2,2) AS UNSIGNED)*3600+CAST(SUBSTRING('__SOURCE_SKILL_OFFSET__',5,2) AS UNSIGNED)*60))*1000000)))));
INSERT INTO compact_skill_guard SELECT NOT EXISTS(SELECT 1 FROM `__SOURCE_SCHEMA__`.agent_skill_audit s WHERE (s.created_at IS NOT NULL AND (CONVERT_TZ(s.created_at,'__SOURCE_SKILL_OFFSET__','+00:00') IS NULL OR NOT(TIMESTAMPDIFF(MICROSECOND,CONVERT_TZ(s.created_at,'__SOURCE_SKILL_OFFSET__','+00:00'),s.created_at)<=>((IF(LEFT('__SOURCE_SKILL_OFFSET__',1)='-',-1,1)*(CAST(SUBSTRING('__SOURCE_SKILL_OFFSET__',2,2) AS UNSIGNED)*3600+CAST(SUBSTRING('__SOURCE_SKILL_OFFSET__',5,2) AS UNSIGNED)*60))*1000000)))));
INSERT INTO compact_skill_guard SELECT NOT EXISTS(SELECT 1 FROM `__SOURCE_SCHEMA__`.agent_skill_import s WHERE (s.created_at IS NOT NULL AND (CONVERT_TZ(s.created_at,'__SOURCE_SKILL_OFFSET__','+00:00') IS NULL OR NOT(TIMESTAMPDIFF(MICROSECOND,CONVERT_TZ(s.created_at,'__SOURCE_SKILL_OFFSET__','+00:00'),s.created_at)<=>((IF(LEFT('__SOURCE_SKILL_OFFSET__',1)='-',-1,1)*(CAST(SUBSTRING('__SOURCE_SKILL_OFFSET__',2,2) AS UNSIGNED)*3600+CAST(SUBSTRING('__SOURCE_SKILL_OFFSET__',5,2) AS UNSIGNED)*60))*1000000)))));
INSERT INTO compact_skill_guard SELECT NOT EXISTS(SELECT 1 FROM `__SOURCE_SCHEMA__`.agent_skill_source s WHERE (s.captured_at IS NOT NULL AND (CONVERT_TZ(s.captured_at,'__SOURCE_SKILL_OFFSET__','+00:00') IS NULL OR NOT(TIMESTAMPDIFF(MICROSECOND,CONVERT_TZ(s.captured_at,'__SOURCE_SKILL_OFFSET__','+00:00'),s.captured_at)<=>((IF(LEFT('__SOURCE_SKILL_OFFSET__',1)='-',-1,1)*(CAST(SUBSTRING('__SOURCE_SKILL_OFFSET__',2,2) AS UNSIGNED)*3600+CAST(SUBSTRING('__SOURCE_SKILL_OFFSET__',5,2) AS UNSIGNED)*60))*1000000)))));
-- END reviewed fixed-offset conversion guards
INSERT INTO compact_skill_guard SELECT
 NOT EXISTS(SELECT 1 FROM content_asset WHERE asset_kind IN ('SKILL','SKILL_IMPORT'))
 AND NOT EXISTS(SELECT 1 FROM content_revision WHERE asset_kind IN ('SKILL','SKILL_IMPORT'))
 AND NOT EXISTS(SELECT 1 FROM workflow_instance WHERE kind='SKILL_IMPORT_COMMAND')
 AND NOT EXISTS(SELECT 1 FROM audit_event WHERE kind IN ('SKILL_EVALUATION','SKILL_AUDIT','SKILL_SOURCE_GRANT'));

-- Never silently filter orphan versions, inconsistent owners or broken publication pointers.
INSERT INTO compact_skill_guard SELECT NOT EXISTS(
 SELECT 1 FROM `__SOURCE_SCHEMA__`.agent_learned_skill s
 LEFT JOIN `__SOURCE_SCHEMA__`.agent_skill_version c ON c.skill_id=s.skill_id AND c.version_no=s.latest_version
 LEFT JOIN `__SOURCE_SCHEMA__`.agent_skill_version p ON p.skill_id=s.skill_id AND p.version_no=s.active_version
 WHERE c.id IS NULL OR c.owner_user_id<>s.owner_user_id OR s.owner_user_id<=0 OR s.revision<1
 OR (s.active_version IS NOT NULL AND (p.id IS NULL OR p.status<>'APPROVED' OR s.active_version>s.latest_version))
 OR CONVERT_TZ(s.created_at,'__SOURCE_SKILL_OFFSET__','+00:00') IS NULL
 OR CONVERT_TZ(s.updated_at,'__SOURCE_SKILL_OFFSET__','+00:00') IS NULL);
INSERT INTO compact_skill_guard SELECT NOT EXISTS(
 SELECT 1 FROM `__SOURCE_SCHEMA__`.agent_skill_version v
 LEFT JOIN `__SOURCE_SCHEMA__`.agent_learned_skill s ON s.skill_id=v.skill_id
 LEFT JOIN `__SOURCE_SCHEMA__`.agent_skill_source g ON g.user_id=v.owner_user_id AND g.run_id=v.source_run_id
 LEFT JOIN `__SOURCE_SCHEMA__`.agent_skill_import i ON i.import_id=v.source_import_id AND i.owner_user_id=v.owner_user_id
 LEFT JOIN `__SOURCE_SCHEMA__`.agent_skill_download d ON d.download_id=v.source_import_id AND d.owner_user_id=v.owner_user_id
 WHERE s.id IS NULL OR s.owner_user_id<>v.owner_user_id OR v.version_no>s.latest_version
 OR v.source_type NOT IN ('RUN','LINK','UPLOAD','EXTERNAL_UPLOAD')
 OR (v.source_type='RUN' AND (g.id IS NULL OR v.source_import_id IS NOT NULL))
 OR (v.source_type IN ('UPLOAD','EXTERNAL_UPLOAD') AND (i.id IS NULL OR v.source_run_id IS NOT NULL))
 OR (v.source_type='LINK' AND (v.source_import_id IS NULL OR v.source_run_id IS NOT NULL
  OR d.id IS NULL OR d.manifest_json IS NULL OR d.manifest_sha256 IS NULL
  OR d.status NOT IN ('DOWNLOADED','DRAFT_CREATED')))
 OR (v.status IN ('APPROVED','REJECTED') AND (v.reviewer_user_id IS NULL OR v.reviewed_at IS NULL))
 OR CONVERT_TZ(v.created_at,'__SOURCE_SKILL_OFFSET__','+00:00') IS NULL);
INSERT INTO compact_skill_guard SELECT NOT EXISTS(
 SELECT 1 FROM `__SOURCE_SCHEMA__`.agent_skill_eval e
 LEFT JOIN `__SOURCE_SCHEMA__`.agent_skill_version v ON v.skill_id=e.skill_id AND v.version_no=e.version_no
 WHERE v.id IS NULL OR e.actor_user_id<=0
 OR CONVERT_TZ(e.created_at,'__SOURCE_SKILL_OFFSET__','+00:00') IS NULL);
INSERT INTO compact_skill_guard SELECT NOT EXISTS(
 SELECT 1 FROM `__SOURCE_SCHEMA__`.agent_skill_audit e
 LEFT JOIN `__SOURCE_SCHEMA__`.agent_skill_version v ON v.skill_id=e.skill_id AND v.version_no=e.version_no
 WHERE v.id IS NULL OR e.actor_user_id<0
 OR CONVERT_TZ(e.created_at,'__SOURCE_SKILL_OFFSET__','+00:00') IS NULL);

INSERT INTO content_asset(asset_id,asset_kind,owner_user_id,title,visibility,required_role,lifecycle,
 current_version,published_version,revision,use_count,last_used_at,activated_at,created_at,updated_at,legacy_source,legacy_id)
SELECT s.skill_id,'SKILL',s.owner_user_id,s.name,IF(s.active_version IS NULL,'PRIVATE','ROLE'),s.target_role,'PREPARING',
 NULL,NULL,s.revision,s.use_count,CONVERT_TZ(s.last_used_at,'__SOURCE_SKILL_OFFSET__','+00:00'),
 CONVERT_TZ(s.activated_at,'__SOURCE_SKILL_OFFSET__','+00:00'),
 CONVERT_TZ(s.created_at,'__SOURCE_SKILL_OFFSET__','+00:00'),CONVERT_TZ(s.updated_at,'__SOURCE_SKILL_OFFSET__','+00:00'),
 'agent_learned_skill',s.id FROM `__SOURCE_SCHEMA__`.agent_learned_skill s ORDER BY s.id;

INSERT INTO content_revision(asset_id,asset_kind,version,owner_user_id,creator_user_id,title,request_id,request_sha256,
 description_text,content_text,tool_names_json,source_run_id,source_type,source_import_id,manifest_json,manifest_sha256,
 content_sha256,stored_content_sha256,byte_length,media_type,approval_status,reviewer_user_id,review_reason,
 submitted_at,reviewed_at,created_at,legacy_source,legacy_id)
SELECT v.skill_id,'SKILL',v.version_no,v.owner_user_id,v.owner_user_id,s.name,v.request_id,v.request_sha256,
 v.description_text,v.instructions_text,CAST(v.tool_names_json AS CHAR CHARACTER SET utf8mb4),v.source_run_id,v.source_type,
 v.source_import_id,CAST(v.evidence_json AS CHAR CHARACTER SET utf8mb4),SHA2(CAST(v.evidence_json AS CHAR CHARACTER SET utf8mb4),256),
 v.content_sha256,SHA2(v.instructions_text,256),OCTET_LENGTH(v.instructions_text),'text/markdown',v.status,
 v.reviewer_user_id,v.review_reason,CONVERT_TZ(v.submitted_at,'__SOURCE_SKILL_OFFSET__','+00:00'),
 CONVERT_TZ(v.reviewed_at,'__SOURCE_SKILL_OFFSET__','+00:00'),CONVERT_TZ(v.created_at,'__SOURCE_SKILL_OFFSET__','+00:00'),
 'agent_skill_version',v.id FROM `__SOURCE_SCHEMA__`.agent_skill_version v
 JOIN `__SOURCE_SCHEMA__`.agent_learned_skill s ON s.skill_id=v.skill_id ORDER BY v.id;

-- Install the cyclic version pointers only after every referenced version exists.
UPDATE content_asset a JOIN `__SOURCE_SCHEMA__`.agent_learned_skill s ON a.asset_id=s.skill_id AND a.asset_kind='SKILL'
 SET a.current_version=s.latest_version,a.published_version=s.active_version,a.lifecycle=s.lifecycle;

-- A source consent is one immutable owner/run fact, not an asset with a fictitious version.
INSERT INTO audit_event(event_id,kind,owner_user_id,actor_user_id,resource_type,resource_id,run_id,
 request_scope,request_id,action,content_sha256,occurred_at,payload_version,payload_json,legacy_source,legacy_key)
SELECT CONCAT('skill-source-',g.id),'SKILL_SOURCE_GRANT',g.user_id,g.user_id,'AGENT_RUN',g.run_id,g.run_id,
 CONCAT('OWNER:',g.user_id),g.run_id,'GRANT_SKILL_SOURCE',g.evidence_sha256,
 CONVERT_TZ(g.captured_at,'__SOURCE_SKILL_OFFSET__','+00:00'),1,
 JSON_OBJECT('evidenceJson',CAST(g.evidence_json AS CHAR CHARACTER SET utf8mb4)),
 'agent_skill_source',CAST(g.id AS CHAR) FROM `__SOURCE_SCHEMA__`.agent_skill_source g ORDER BY g.id;

-- Removed upload functionality still has an original package and request receipt to retain.
INSERT INTO content_asset(asset_id,asset_kind,owner_user_id,title,visibility,lifecycle,current_version,revision,
 created_at,updated_at,legacy_source,legacy_id)
SELECT i.import_id,'SKILL_IMPORT',i.owner_user_id,'历史技能上传包','PRIVATE','PREPARING',NULL,1,
 CONVERT_TZ(i.created_at,'__SOURCE_SKILL_OFFSET__','+00:00'),CONVERT_TZ(i.created_at,'__SOURCE_SKILL_OFFSET__','+00:00'),
 'agent_skill_import',i.id FROM `__SOURCE_SCHEMA__`.agent_skill_import i ORDER BY i.id;
INSERT INTO content_revision(asset_id,asset_kind,version,owner_user_id,creator_user_id,
 source_type,manifest_json,manifest_sha256,content_sha256,stored_content_sha256,created_at,legacy_source,legacy_id)
SELECT i.import_id,'SKILL_IMPORT',1,i.owner_user_id,i.owner_user_id,'EXTERNAL_UPLOAD',
 CAST(i.payload_json AS CHAR CHARACTER SET utf8mb4),i.payload_sha256,i.payload_sha256,
 SHA2(CAST(i.payload_json AS CHAR CHARACTER SET utf8mb4),256),
 CONVERT_TZ(i.created_at,'__SOURCE_SKILL_OFFSET__','+00:00'),'agent_skill_import',i.id
 FROM `__SOURCE_SCHEMA__`.agent_skill_import i ORDER BY i.id;
UPDATE content_asset SET current_version=1,lifecycle='ARCHIVED' WHERE asset_kind='SKILL_IMPORT';

-- The request identity survives independently of package retention; no new upload API is enabled.
INSERT INTO workflow_instance(workflow_id,kind,idempotency_scope,request_id,request_sha256,owner_user_id,
 actor_user_id,resource_type,resource_id,resource_revision,status,revision,fence,payload_version,payload_json,
 created_at,updated_at,finished_at,legacy_source,legacy_key)
SELECT CONCAT('skill-import-',i.id),'SKILL_IMPORT_COMMAND',CONCAT('OWNER:',i.owner_user_id),i.request_id,i.request_sha256,
 i.owner_user_id,i.owner_user_id,'SKILL_IMPORT',i.import_id,1,'COMPLETED',0,0,1,
 JSON_OBJECT('importId',i.import_id,'packageSha256',i.payload_sha256),
 CONVERT_TZ(i.created_at,'__SOURCE_SKILL_OFFSET__','+00:00'),CONVERT_TZ(i.created_at,'__SOURCE_SKILL_OFFSET__','+00:00'),
 CONVERT_TZ(i.created_at,'__SOURCE_SKILL_OFFSET__','+00:00'),'agent_skill_import',CAST(i.id AS CHAR)
 FROM `__SOURCE_SCHEMA__`.agent_skill_import i ORDER BY i.id;

INSERT INTO audit_event(event_id,kind,owner_user_id,actor_user_id,resource_type,resource_id,action,revision,
 content_sha256,policy_version,outcome,occurred_at,payload_version,payload_json,legacy_source,legacy_key)
SELECT CONCAT('skill-eval-',e.id),'SKILL_EVALUATION',s.owner_user_id,e.actor_user_id,'SKILL',e.skill_id,'EVALUATE',e.version_no,
 e.content_sha256,e.suite_version,IF(e.passed,'PASSED','FAILED'),CONVERT_TZ(e.created_at,'__SOURCE_SKILL_OFFSET__','+00:00'),1,
 JSON_OBJECT('skillId',e.skill_id,'version',e.version_no,'suiteVersion',e.suite_version,'result',e.result_json),
 'agent_skill_eval',CAST(e.id AS CHAR) FROM `__SOURCE_SCHEMA__`.agent_skill_eval e
 JOIN `__SOURCE_SCHEMA__`.agent_learned_skill s ON s.skill_id=e.skill_id ORDER BY e.id;
INSERT INTO audit_event(event_id,kind,owner_user_id,actor_user_id,resource_type,resource_id,run_id,action,revision,
 content_sha256,occurred_at,payload_version,payload_json,legacy_source,legacy_key)
SELECT CONCAT('skill-audit-',e.id),'SKILL_AUDIT',s.owner_user_id,NULLIF(e.actor_user_id,0),'SKILL',e.skill_id,e.run_id,e.action_name,
 e.revision,e.content_sha256,CONVERT_TZ(e.created_at,'__SOURCE_SKILL_OFFSET__','+00:00'),1,
 JSON_OBJECT('version',e.version_no,'reason',e.reason,'callId',e.call_id,'systemActor',CAST(IF(e.actor_user_id=0,'true','false') AS JSON)),
 'agent_skill_audit',CAST(e.id AS CHAR) FROM `__SOURCE_SCHEMA__`.agent_skill_audit e
 JOIN `__SOURCE_SCHEMA__`.agent_learned_skill s ON s.skill_id=e.skill_id ORDER BY e.id;

-- Count parity is necessary; per-row bytes, ownership, version pointers and gate values are checked below as well.
INSERT INTO compact_skill_guard SELECT
 (SELECT COUNT(*) FROM `__SOURCE_SCHEMA__`.agent_learned_skill)=(SELECT COUNT(*) FROM content_asset WHERE asset_kind='SKILL')
 AND (SELECT COUNT(*) FROM `__SOURCE_SCHEMA__`.agent_skill_version)=(SELECT COUNT(*) FROM content_revision WHERE asset_kind='SKILL')
 AND (SELECT COUNT(*) FROM `__SOURCE_SCHEMA__`.agent_skill_source)=(SELECT COUNT(*) FROM audit_event WHERE kind='SKILL_SOURCE_GRANT')
 AND (SELECT COUNT(*) FROM `__SOURCE_SCHEMA__`.agent_skill_import)=(SELECT COUNT(*) FROM content_asset WHERE asset_kind='SKILL_IMPORT')
 AND (SELECT COUNT(*) FROM `__SOURCE_SCHEMA__`.agent_skill_import)=(SELECT COUNT(*) FROM content_revision WHERE asset_kind='SKILL_IMPORT')
 AND (SELECT COUNT(*) FROM `__SOURCE_SCHEMA__`.agent_skill_import)=(SELECT COUNT(*) FROM workflow_instance WHERE kind='SKILL_IMPORT_COMMAND')
 AND (SELECT COUNT(*) FROM `__SOURCE_SCHEMA__`.agent_skill_eval)=(SELECT COUNT(*) FROM audit_event WHERE kind='SKILL_EVALUATION')
 AND (SELECT COUNT(*) FROM `__SOURCE_SCHEMA__`.agent_skill_audit)=(SELECT COUNT(*) FROM audit_event WHERE kind='SKILL_AUDIT');
INSERT INTO compact_skill_guard SELECT NOT EXISTS(
 SELECT 1 FROM `__SOURCE_SCHEMA__`.agent_learned_skill s
 LEFT JOIN content_asset a ON a.legacy_source='agent_learned_skill' AND a.legacy_id=s.id
 WHERE a.id IS NULL OR BINARY a.asset_id<>BINARY s.skill_id OR a.owner_user_id<>s.owner_user_id
 OR BINARY a.title<>BINARY s.name OR a.required_role<>s.target_role OR a.current_version<>s.latest_version
 OR NOT(a.published_version<=>s.active_version) OR a.revision<>s.revision OR a.lifecycle<>s.lifecycle OR a.use_count<>s.use_count
 OR NOT(a.last_used_at<=>CONVERT_TZ(s.last_used_at,'__SOURCE_SKILL_OFFSET__','+00:00'))
 OR NOT(a.activated_at<=>CONVERT_TZ(s.activated_at,'__SOURCE_SKILL_OFFSET__','+00:00'))
 OR a.created_at<>CONVERT_TZ(s.created_at,'__SOURCE_SKILL_OFFSET__','+00:00')
 OR a.updated_at<>CONVERT_TZ(s.updated_at,'__SOURCE_SKILL_OFFSET__','+00:00'));
INSERT INTO compact_skill_guard SELECT NOT EXISTS(
 SELECT 1 FROM `__SOURCE_SCHEMA__`.agent_skill_version v
 LEFT JOIN content_revision r ON r.legacy_source='agent_skill_version' AND r.legacy_id=v.id
 WHERE r.id IS NULL OR BINARY r.asset_id<>BINARY v.skill_id OR r.version<>v.version_no OR r.owner_user_id<>v.owner_user_id
 OR BINARY r.request_id<>BINARY v.request_id OR BINARY r.request_sha256<>BINARY v.request_sha256
 OR BINARY r.description_text<>BINARY v.description_text OR BINARY r.content_text<>BINARY v.instructions_text
 OR BINARY r.tool_names_json<>BINARY CAST(v.tool_names_json AS CHAR CHARACTER SET utf8mb4)
 OR BINARY r.manifest_json<>BINARY CAST(v.evidence_json AS CHAR CHARACTER SET utf8mb4)
 OR BINARY r.content_sha256<>BINARY v.content_sha256 OR r.stored_content_sha256<>SHA2(v.instructions_text,256)
 OR r.source_type<>v.source_type OR NOT(BINARY r.source_run_id<=>BINARY v.source_run_id)
 OR NOT(BINARY r.source_import_id<=>BINARY v.source_import_id) OR r.approval_status<>v.status
 OR NOT(r.reviewer_user_id<=>v.reviewer_user_id) OR NOT(BINARY r.review_reason<=>BINARY v.review_reason)
 OR NOT(r.submitted_at<=>CONVERT_TZ(v.submitted_at,'__SOURCE_SKILL_OFFSET__','+00:00'))
 OR NOT(r.reviewed_at<=>CONVERT_TZ(v.reviewed_at,'__SOURCE_SKILL_OFFSET__','+00:00'))
 OR r.created_at<>CONVERT_TZ(v.created_at,'__SOURCE_SKILL_OFFSET__','+00:00'));
INSERT INTO compact_skill_guard SELECT NOT EXISTS(
 SELECT 1 FROM `__SOURCE_SCHEMA__`.agent_skill_source g
 LEFT JOIN audit_event a ON a.kind='SKILL_SOURCE_GRANT' AND a.legacy_source='agent_skill_source' AND a.legacy_key=CAST(g.id AS CHAR)
 WHERE a.id IS NULL OR a.owner_user_id<>g.user_id OR a.actor_user_id<>g.user_id
 OR BINARY a.run_id<>BINARY g.run_id OR BINARY a.resource_id<>BINARY g.run_id
 OR BINARY a.request_id<>BINARY g.run_id OR a.request_scope<>CONCAT('OWNER:',g.user_id)
 OR BINARY a.content_sha256<>BINARY g.evidence_sha256
 OR BINARY JSON_UNQUOTE(JSON_EXTRACT(a.payload_json,'$.evidenceJson'))<>BINARY CAST(g.evidence_json AS CHAR CHARACTER SET utf8mb4)
 OR a.occurred_at<>CONVERT_TZ(g.captured_at,'__SOURCE_SKILL_OFFSET__','+00:00'));
INSERT INTO compact_skill_guard SELECT NOT EXISTS(
 SELECT 1 FROM `__SOURCE_SCHEMA__`.agent_skill_import i
 LEFT JOIN content_revision r ON r.legacy_source='agent_skill_import' AND r.legacy_id=i.id
 LEFT JOIN workflow_instance w ON w.kind='SKILL_IMPORT_COMMAND' AND w.legacy_source='agent_skill_import' AND w.legacy_key=CAST(i.id AS CHAR)
 WHERE r.id IS NULL OR BINARY r.asset_id<>BINARY i.import_id OR r.owner_user_id<>i.owner_user_id
 OR w.id IS NULL OR BINARY w.request_id<>BINARY i.request_id OR BINARY w.request_sha256<>BINARY i.request_sha256
 OR w.owner_user_id<>i.owner_user_id OR BINARY w.resource_id<>BINARY i.import_id OR w.status<>'COMPLETED'
 OR w.idempotency_scope<>CONCAT('OWNER:',i.owner_user_id)
 OR BINARY JSON_UNQUOTE(JSON_EXTRACT(w.payload_json,'$.packageSha256'))<>BINARY i.payload_sha256
 OR BINARY r.manifest_sha256<>BINARY i.payload_sha256
 OR BINARY r.manifest_json<>BINARY CAST(i.payload_json AS CHAR CHARACTER SET utf8mb4)
 OR r.created_at<>CONVERT_TZ(i.created_at,'__SOURCE_SKILL_OFFSET__','+00:00'));
INSERT INTO compact_skill_guard SELECT NOT EXISTS(
 SELECT 1 FROM `__SOURCE_SCHEMA__`.agent_skill_eval e
 LEFT JOIN audit_event a ON a.legacy_source='agent_skill_eval' AND a.legacy_key=CAST(e.id AS CHAR)
 WHERE a.id IS NULL OR BINARY a.resource_id<>BINARY e.skill_id OR a.revision<>e.version_no
 OR a.actor_user_id<>e.actor_user_id OR a.policy_version<>e.suite_version OR a.outcome<>IF(e.passed,'PASSED','FAILED')
 OR BINARY a.content_sha256<>BINARY e.content_sha256 OR JSON_EXTRACT(a.payload_json,'$.result')<>e.result_json
 OR a.occurred_at<>CONVERT_TZ(e.created_at,'__SOURCE_SKILL_OFFSET__','+00:00'));
INSERT INTO compact_skill_guard SELECT NOT EXISTS(
 SELECT 1 FROM `__SOURCE_SCHEMA__`.agent_skill_audit e
 LEFT JOIN audit_event a ON a.legacy_source='agent_skill_audit' AND a.legacy_key=CAST(e.id AS CHAR)
 WHERE a.id IS NULL OR BINARY a.resource_id<>BINARY e.skill_id OR a.revision<>e.revision
 OR COALESCE(a.actor_user_id,0)<>e.actor_user_id OR a.action<>e.action_name OR BINARY a.content_sha256<>BINARY e.content_sha256
 OR NOT(BINARY a.run_id<=>BINARY e.run_id) OR JSON_EXTRACT(a.payload_json,'$.version')<>e.version_no
 OR NOT(JSON_EXTRACT(a.payload_json,'$.reason')<=>JSON_EXTRACT(JSON_OBJECT('reason',e.reason),'$.reason'))
 OR NOT(JSON_EXTRACT(a.payload_json,'$.callId')<=>JSON_EXTRACT(JSON_OBJECT('callId',e.call_id),'$.callId'))
 OR a.occurred_at<>CONVERT_TZ(e.created_at,'__SOURCE_SKILL_OFFSET__','+00:00'));
COMMIT;
DROP TEMPORARY TABLE compact_skill_guard;
