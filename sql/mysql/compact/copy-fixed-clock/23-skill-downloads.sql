-- Isolated ECS target only, after 22-skills.sql, with source writers stopped.
-- Replace __SOURCE_SCHEMA__ only as a validated identifier and supply the observed
-- __SOURCE_SKILL_OFFSET__. Stop on the first SQL error and ROLLBACK on this connection.
-- Lease expiry is never converted into proof that an external process exited.
CREATE TEMPORARY TABLE compact_skill_download_guard(ok TINYINT NOT NULL CHECK(ok=1));
START TRANSACTION;
-- BEGIN reviewed fixed-offset conversion guards
INSERT INTO compact_skill_download_guard SELECT IF(REGEXP_LIKE('__SOURCE_SKILL_OFFSET__','^[+-][0-9]{2}:[0-9]{2}$','c') AND CONVERT_TZ('2026-01-01','__SOURCE_SKILL_OFFSET__','+00:00') IS NOT NULL,1,0);
INSERT INTO compact_skill_download_guard SELECT NOT EXISTS(SELECT 1 FROM `__SOURCE_SCHEMA__`.agent_skill_download s WHERE (s.created_at IS NOT NULL AND (CONVERT_TZ(s.created_at,'__SOURCE_SKILL_OFFSET__','+00:00') IS NULL OR NOT(TIMESTAMPDIFF(MICROSECOND,CONVERT_TZ(s.created_at,'__SOURCE_SKILL_OFFSET__','+00:00'),s.created_at)<=>((IF(LEFT('__SOURCE_SKILL_OFFSET__',1)='-',-1,1)*(CAST(SUBSTRING('__SOURCE_SKILL_OFFSET__',2,2) AS SIGNED)*3600+CAST(SUBSTRING('__SOURCE_SKILL_OFFSET__',5,2) AS SIGNED)*60))*1000000)))) OR (s.updated_at IS NOT NULL AND (CONVERT_TZ(s.updated_at,'__SOURCE_SKILL_OFFSET__','+00:00') IS NULL OR NOT(TIMESTAMPDIFF(MICROSECOND,CONVERT_TZ(s.updated_at,'__SOURCE_SKILL_OFFSET__','+00:00'),s.updated_at)<=>((IF(LEFT('__SOURCE_SKILL_OFFSET__',1)='-',-1,1)*(CAST(SUBSTRING('__SOURCE_SKILL_OFFSET__',2,2) AS SIGNED)*3600+CAST(SUBSTRING('__SOURCE_SKILL_OFFSET__',5,2) AS SIGNED)*60))*1000000)))));
INSERT INTO compact_skill_download_guard SELECT NOT EXISTS(SELECT 1 FROM `__SOURCE_SCHEMA__`.agent_skill_download_event s WHERE (s.created_at IS NOT NULL AND (CONVERT_TZ(s.created_at,'__SOURCE_SKILL_OFFSET__','+00:00') IS NULL OR NOT(TIMESTAMPDIFF(MICROSECOND,CONVERT_TZ(s.created_at,'__SOURCE_SKILL_OFFSET__','+00:00'),s.created_at)<=>((IF(LEFT('__SOURCE_SKILL_OFFSET__',1)='-',-1,1)*(CAST(SUBSTRING('__SOURCE_SKILL_OFFSET__',2,2) AS SIGNED)*3600+CAST(SUBSTRING('__SOURCE_SKILL_OFFSET__',5,2) AS SIGNED)*60))*1000000)))));
INSERT INTO compact_skill_download_guard SELECT NOT EXISTS(SELECT 1 FROM `__SOURCE_SCHEMA__`.agent_skill_download_lease s WHERE (s.created_at IS NOT NULL AND (CONVERT_TZ(s.created_at,'__SOURCE_SKILL_OFFSET__','+00:00') IS NULL OR NOT(TIMESTAMPDIFF(MICROSECOND,CONVERT_TZ(s.created_at,'__SOURCE_SKILL_OFFSET__','+00:00'),s.created_at)<=>((IF(LEFT('__SOURCE_SKILL_OFFSET__',1)='-',-1,1)*(CAST(SUBSTRING('__SOURCE_SKILL_OFFSET__',2,2) AS SIGNED)*3600+CAST(SUBSTRING('__SOURCE_SKILL_OFFSET__',5,2) AS SIGNED)*60))*1000000)))) OR (s.updated_at IS NOT NULL AND (CONVERT_TZ(s.updated_at,'__SOURCE_SKILL_OFFSET__','+00:00') IS NULL OR NOT(TIMESTAMPDIFF(MICROSECOND,CONVERT_TZ(s.updated_at,'__SOURCE_SKILL_OFFSET__','+00:00'),s.updated_at)<=>((IF(LEFT('__SOURCE_SKILL_OFFSET__',1)='-',-1,1)*(CAST(SUBSTRING('__SOURCE_SKILL_OFFSET__',2,2) AS SIGNED)*3600+CAST(SUBSTRING('__SOURCE_SKILL_OFFSET__',5,2) AS SIGNED)*60))*1000000)))) OR (s.lease_expires_at IS NOT NULL AND (CONVERT_TZ(s.lease_expires_at,'__SOURCE_SKILL_OFFSET__','+00:00') IS NULL OR NOT(TIMESTAMPDIFF(MICROSECOND,CONVERT_TZ(s.lease_expires_at,'__SOURCE_SKILL_OFFSET__','+00:00'),s.lease_expires_at)<=>((IF(LEFT('__SOURCE_SKILL_OFFSET__',1)='-',-1,1)*(CAST(SUBSTRING('__SOURCE_SKILL_OFFSET__',2,2) AS SIGNED)*3600+CAST(SUBSTRING('__SOURCE_SKILL_OFFSET__',5,2) AS SIGNED)*60))*1000000)))));
INSERT INTO compact_skill_download_guard SELECT NOT EXISTS(SELECT 1 FROM `__SOURCE_SCHEMA__`.agent_skill_storage_command s WHERE (s.created_at IS NOT NULL AND (CONVERT_TZ(s.created_at,'__SOURCE_SKILL_OFFSET__','+00:00') IS NULL OR NOT(TIMESTAMPDIFF(MICROSECOND,CONVERT_TZ(s.created_at,'__SOURCE_SKILL_OFFSET__','+00:00'),s.created_at)<=>((IF(LEFT('__SOURCE_SKILL_OFFSET__',1)='-',-1,1)*(CAST(SUBSTRING('__SOURCE_SKILL_OFFSET__',2,2) AS SIGNED)*3600+CAST(SUBSTRING('__SOURCE_SKILL_OFFSET__',5,2) AS SIGNED)*60))*1000000)))) OR (s.updated_at IS NOT NULL AND (CONVERT_TZ(s.updated_at,'__SOURCE_SKILL_OFFSET__','+00:00') IS NULL OR NOT(TIMESTAMPDIFF(MICROSECOND,CONVERT_TZ(s.updated_at,'__SOURCE_SKILL_OFFSET__','+00:00'),s.updated_at)<=>((IF(LEFT('__SOURCE_SKILL_OFFSET__',1)='-',-1,1)*(CAST(SUBSTRING('__SOURCE_SKILL_OFFSET__',2,2) AS SIGNED)*3600+CAST(SUBSTRING('__SOURCE_SKILL_OFFSET__',5,2) AS SIGNED)*60))*1000000)))));
-- END reviewed fixed-offset conversion guards
INSERT INTO compact_skill_download_guard SELECT
 NOT EXISTS(SELECT 1 FROM workflow_instance WHERE kind IN ('SKILL_DOWNLOAD','SKILL_STORAGE_COMMAND'))
 AND NOT EXISTS(SELECT 1 FROM audit_event WHERE kind='SKILL_DOWNLOAD_EVENT')
 AND NOT EXISTS(SELECT 1 FROM content_asset WHERE legacy_source='agent_skill_download');
-- Recheck both the original and already-copied references. A source change between
-- the two scripts must fail before any download or package is written.
INSERT INTO compact_skill_download_guard SELECT NOT EXISTS(
 SELECT 1 FROM `__SOURCE_SCHEMA__`.agent_skill_version v
 LEFT JOIN `__SOURCE_SCHEMA__`.agent_skill_download d ON d.download_id=v.source_import_id AND d.owner_user_id=v.owner_user_id
 WHERE v.source_type='LINK' AND (d.id IS NULL OR d.manifest_json IS NULL OR d.manifest_sha256 IS NULL
  OR d.status NOT IN ('DOWNLOADED','DRAFT_CREATED')));
INSERT INTO compact_skill_download_guard SELECT NOT EXISTS(
 SELECT 1 FROM content_revision v
 LEFT JOIN `__SOURCE_SCHEMA__`.agent_skill_download d ON d.download_id=v.source_import_id AND d.owner_user_id=v.owner_user_id
 WHERE v.asset_kind='SKILL' AND v.source_type='LINK' AND (d.id IS NULL OR d.manifest_json IS NULL OR d.manifest_sha256 IS NULL
  OR d.status NOT IN ('DOWNLOADED','DRAFT_CREATED')));
INSERT INTO compact_skill_download_guard SELECT NOT EXISTS(
 SELECT 1 FROM `__SOURCE_SCHEMA__`.agent_skill_download d
 WHERE d.owner_user_id<=0 OR d.status NOT IN ('DOWNLOADING','DOWNLOADED','DRAFT_CREATED','NO_CHANGE','ERROR','NEEDS_REVIEW','PURGING','PURGED','CLEANUP_ERROR')
 OR (d.target_skill_id IS NULL)<>(d.expected_skill_revision IS NULL)
 OR (d.manifest_json IS NULL)<>(d.manifest_sha256 IS NULL)
 OR CONVERT_TZ(d.created_at,'__SOURCE_SKILL_OFFSET__','+00:00') IS NULL
 OR CONVERT_TZ(d.updated_at,'__SOURCE_SKILL_OFFSET__','+00:00') IS NULL);
INSERT INTO compact_skill_download_guard SELECT NOT EXISTS(
 SELECT 1 FROM `__SOURCE_SCHEMA__`.agent_skill_download_lease l
 LEFT JOIN `__SOURCE_SCHEMA__`.agent_skill_download d ON d.download_id=l.download_id AND d.owner_user_id=l.owner_user_id
 WHERE d.id IS NULL OR l.status NOT IN ('RESERVED','RUNNING','SEALED','RELEASED','NEEDS_REVIEW') OR l.reserved_bytes<0
 OR (l.status IN ('SEALED','RELEASED') AND (l.exit_verified<>TRUE OR l.reserved_bytes<>0))
 OR (l.status IN ('RESERVED','RUNNING','NEEDS_REVIEW') AND l.exit_verified<>FALSE)
 OR CONVERT_TZ(l.lease_expires_at,'__SOURCE_SKILL_OFFSET__','+00:00') IS NULL
 OR CONVERT_TZ(l.created_at,'__SOURCE_SKILL_OFFSET__','+00:00') IS NULL
 OR CONVERT_TZ(l.updated_at,'__SOURCE_SKILL_OFFSET__','+00:00') IS NULL);
INSERT INTO compact_skill_download_guard SELECT NOT EXISTS(
 SELECT 1 FROM `__SOURCE_SCHEMA__`.agent_skill_storage_command c
 LEFT JOIN `__SOURCE_SCHEMA__`.agent_skill_download d ON d.download_id=c.download_id AND d.owner_user_id=c.owner_user_id
 WHERE d.id IS NULL OR c.status NOT IN ('STARTED','COMPLETED','ERROR') OR c.removed_bytes<0 OR c.removed_files<0);
INSERT INTO compact_skill_download_guard SELECT NOT EXISTS(
 SELECT 1 FROM `__SOURCE_SCHEMA__`.agent_skill_download_event e
 LEFT JOIN `__SOURCE_SCHEMA__`.agent_skill_download d ON d.download_id=e.download_id AND d.owner_user_id=e.owner_user_id
 WHERE d.id IS NULL);

INSERT INTO workflow_instance(workflow_id,kind,idempotency_scope,request_id,request_sha256,owner_user_id,actor_user_id,
 resource_type,resource_id,resource_revision,status,error_code,revision,fence,payload_version,payload_json,
 execution_state,reserved_bytes,exit_verified,execution_deadline,created_at,updated_at,finished_at,legacy_source,legacy_key)
SELECT d.download_id,'SKILL_DOWNLOAD',CONCAT('OWNER:',d.owner_user_id),d.request_id,d.request_sha256,d.owner_user_id,d.owner_user_id,
 'SKILL_DOWNLOAD',d.download_id,1,d.status,d.error_code,0,0,1,
 JSON_OBJECT('sourceUrl',d.source_url,'targetRole',d.target_role,'targetSkillId',d.target_skill_id,
 'expectedSkillRevision',d.expected_skill_revision,'skillId',d.skill_id,
 'lease',IF(l.download_id IS NULL,CAST('null' AS JSON),JSON_OBJECT('workerInstance',l.worker_instance,
 'processPid',l.process_pid,'processStartedAt',l.process_started_at,
 'createdAt',DATE_FORMAT(CONVERT_TZ(l.created_at,'__SOURCE_SKILL_OFFSET__','+00:00'),'%Y-%m-%dT%H:%i:%s.%f'),
 'updatedAt',DATE_FORMAT(CONVERT_TZ(l.updated_at,'__SOURCE_SKILL_OFFSET__','+00:00'),'%Y-%m-%dT%H:%i:%s.%f')))),
 l.status,l.reserved_bytes,l.exit_verified,CONVERT_TZ(l.lease_expires_at,'__SOURCE_SKILL_OFFSET__','+00:00'),
 CONVERT_TZ(d.created_at,'__SOURCE_SKILL_OFFSET__','+00:00'),CONVERT_TZ(d.updated_at,'__SOURCE_SKILL_OFFSET__','+00:00'),
 IF(d.status='PURGED',CONVERT_TZ(d.updated_at,'__SOURCE_SKILL_OFFSET__','+00:00'),NULL),
 'agent_skill_download',CAST(d.id AS CHAR)
 FROM `__SOURCE_SCHEMA__`.agent_skill_download d LEFT JOIN `__SOURCE_SCHEMA__`.agent_skill_download_lease l ON l.download_id=d.download_id
 ORDER BY d.id;

-- Only downloads which actually have a manifest become content; pending jobs do not get fictitious assets.
INSERT INTO content_asset(asset_id,asset_kind,owner_user_id,title,visibility,lifecycle,current_version,revision,
 created_at,updated_at,legacy_source,legacy_id)
SELECT d.download_id,'SKILL_IMPORT',d.owner_user_id,'链接技能包','PRIVATE','PREPARING',NULL,1,
 CONVERT_TZ(d.created_at,'__SOURCE_SKILL_OFFSET__','+00:00'),CONVERT_TZ(d.updated_at,'__SOURCE_SKILL_OFFSET__','+00:00'),
 'agent_skill_download',d.id FROM `__SOURCE_SCHEMA__`.agent_skill_download d WHERE d.manifest_json IS NOT NULL ORDER BY d.id;
INSERT INTO content_revision(asset_id,asset_kind,version,owner_user_id,creator_user_id,source_type,
 manifest_json,manifest_sha256,stored_content_sha256,created_at,legacy_source,legacy_id)
SELECT d.download_id,'SKILL_IMPORT',1,d.owner_user_id,d.owner_user_id,'LINK',CAST(d.manifest_json AS CHAR CHARACTER SET utf8mb4),
 d.manifest_sha256,SHA2(CAST(d.manifest_json AS CHAR CHARACTER SET utf8mb4),256),
 CONVERT_TZ(d.created_at,'__SOURCE_SKILL_OFFSET__','+00:00'),'agent_skill_download',d.id
 FROM `__SOURCE_SCHEMA__`.agent_skill_download d WHERE d.manifest_json IS NOT NULL ORDER BY d.id;
UPDATE content_asset a JOIN `__SOURCE_SCHEMA__`.agent_skill_download d ON a.asset_id=d.download_id AND a.legacy_source='agent_skill_download'
 SET a.current_version=1,a.lifecycle=IF(d.status='PURGED','ARCHIVED','ACTIVE');

INSERT INTO workflow_instance(workflow_id,kind,idempotency_scope,request_id,request_sha256,owner_user_id,actor_user_id,
 resource_type,resource_id,resource_revision,status,error_code,revision,fence,payload_version,payload_json,
 created_at,updated_at,finished_at,legacy_source,legacy_key)
SELECT CONCAT('skill-cleanup-',c.id),'SKILL_STORAGE_COMMAND',CONCAT('OWNER:',c.owner_user_id),c.request_id,c.request_sha256,
 c.owner_user_id,c.owner_user_id,'SKILL_DOWNLOAD',c.download_id,1,c.status,c.error_code,0,0,1,
 JSON_OBJECT('downloadId',c.download_id,'removedBytes',c.removed_bytes,'removedFiles',c.removed_files),
 CONVERT_TZ(c.created_at,'__SOURCE_SKILL_OFFSET__','+00:00'),CONVERT_TZ(c.updated_at,'__SOURCE_SKILL_OFFSET__','+00:00'),
 IF(c.status='STARTED',NULL,CONVERT_TZ(c.updated_at,'__SOURCE_SKILL_OFFSET__','+00:00')),
 'agent_skill_storage_command',CAST(c.id AS CHAR) FROM `__SOURCE_SCHEMA__`.agent_skill_storage_command c ORDER BY c.id;
INSERT INTO audit_event(event_id,kind,owner_user_id,resource_type,resource_id,action,occurred_at,payload_version,payload_json,legacy_source,legacy_key)
SELECT CONCAT('skill-download-event-',e.id),'SKILL_DOWNLOAD_EVENT',e.owner_user_id,'SKILL_DOWNLOAD',e.download_id,e.action,
 CONVERT_TZ(e.created_at,'__SOURCE_SKILL_OFFSET__','+00:00'),1,JSON_OBJECT('status',e.status),'agent_skill_download_event',CAST(e.id AS CHAR)
 FROM `__SOURCE_SCHEMA__`.agent_skill_download_event e ORDER BY e.id;

INSERT INTO compact_skill_download_guard SELECT
 (SELECT COUNT(*) FROM `__SOURCE_SCHEMA__`.agent_skill_download)=(SELECT COUNT(*) FROM workflow_instance WHERE kind='SKILL_DOWNLOAD')
 AND (SELECT COUNT(*) FROM `__SOURCE_SCHEMA__`.agent_skill_download_lease)=(SELECT COUNT(*) FROM workflow_instance WHERE kind='SKILL_DOWNLOAD' AND execution_state IS NOT NULL)
 AND (SELECT COUNT(*) FROM `__SOURCE_SCHEMA__`.agent_skill_download WHERE manifest_json IS NOT NULL)=(SELECT COUNT(*) FROM content_revision WHERE legacy_source='agent_skill_download')
 AND (SELECT COUNT(*) FROM `__SOURCE_SCHEMA__`.agent_skill_storage_command)=(SELECT COUNT(*) FROM workflow_instance WHERE kind='SKILL_STORAGE_COMMAND')
 AND (SELECT COUNT(*) FROM `__SOURCE_SCHEMA__`.agent_skill_download_event)=(SELECT COUNT(*) FROM audit_event WHERE kind='SKILL_DOWNLOAD_EVENT');
INSERT INTO compact_skill_download_guard SELECT NOT EXISTS(
 SELECT 1 FROM `__SOURCE_SCHEMA__`.agent_skill_download d
 LEFT JOIN workflow_instance w ON w.kind='SKILL_DOWNLOAD' AND w.legacy_source='agent_skill_download' AND w.legacy_key=CAST(d.id AS CHAR)
 WHERE w.id IS NULL OR BINARY w.workflow_id<>BINARY d.download_id OR w.owner_user_id<>d.owner_user_id
 OR BINARY w.request_id<>BINARY d.request_id OR BINARY w.request_sha256<>BINARY d.request_sha256
 OR w.idempotency_scope<>CONCAT('OWNER:',d.owner_user_id) OR w.status<>d.status OR NOT(BINARY w.error_code<=>BINARY d.error_code)
 OR BINARY JSON_UNQUOTE(JSON_EXTRACT(w.payload_json,'$.sourceUrl'))<>BINARY d.source_url
 OR JSON_UNQUOTE(JSON_EXTRACT(w.payload_json,'$.targetRole'))<>d.target_role
 OR NOT(JSON_EXTRACT(w.payload_json,'$.targetSkillId')<=>JSON_EXTRACT(JSON_OBJECT('v',d.target_skill_id),'$.v'))
 OR NOT(JSON_EXTRACT(w.payload_json,'$.expectedSkillRevision')<=>JSON_EXTRACT(JSON_OBJECT('v',d.expected_skill_revision),'$.v'))
 OR NOT(JSON_EXTRACT(w.payload_json,'$.skillId')<=>JSON_EXTRACT(JSON_OBJECT('v',d.skill_id),'$.v'))
 OR w.created_at<>CONVERT_TZ(d.created_at,'__SOURCE_SKILL_OFFSET__','+00:00') OR w.updated_at<>CONVERT_TZ(d.updated_at,'__SOURCE_SKILL_OFFSET__','+00:00'));
INSERT INTO compact_skill_download_guard SELECT NOT EXISTS(
 SELECT 1 FROM `__SOURCE_SCHEMA__`.agent_skill_download_lease l
 LEFT JOIN workflow_instance w ON w.kind='SKILL_DOWNLOAD' AND w.workflow_id=l.download_id
 WHERE w.id IS NULL OR w.owner_user_id<>l.owner_user_id OR w.execution_state<>l.status OR w.reserved_bytes<>l.reserved_bytes OR w.exit_verified<>l.exit_verified
 OR w.execution_deadline<>CONVERT_TZ(l.lease_expires_at,'__SOURCE_SKILL_OFFSET__','+00:00')
 OR NOT(JSON_EXTRACT(w.payload_json,'$.lease.workerInstance')<=>JSON_EXTRACT(JSON_OBJECT('v',l.worker_instance),'$.v'))
 OR NOT(JSON_EXTRACT(w.payload_json,'$.lease.processPid')<=>JSON_EXTRACT(JSON_OBJECT('v',l.process_pid),'$.v'))
 OR NOT(JSON_EXTRACT(w.payload_json,'$.lease.processStartedAt')<=>JSON_EXTRACT(JSON_OBJECT('v',l.process_started_at),'$.v'))
 OR JSON_UNQUOTE(JSON_EXTRACT(w.payload_json,'$.lease.createdAt'))<>DATE_FORMAT(CONVERT_TZ(l.created_at,'__SOURCE_SKILL_OFFSET__','+00:00'),'%Y-%m-%dT%H:%i:%s.%f')
 OR JSON_UNQUOTE(JSON_EXTRACT(w.payload_json,'$.lease.updatedAt'))<>DATE_FORMAT(CONVERT_TZ(l.updated_at,'__SOURCE_SKILL_OFFSET__','+00:00'),'%Y-%m-%dT%H:%i:%s.%f'));
INSERT INTO compact_skill_download_guard SELECT NOT EXISTS(
 SELECT 1 FROM `__SOURCE_SCHEMA__`.agent_skill_download d LEFT JOIN content_revision r ON r.asset_id=d.download_id AND r.asset_kind='SKILL_IMPORT' AND r.version=1
 WHERE d.manifest_json IS NOT NULL AND (r.id IS NULL OR r.owner_user_id<>d.owner_user_id OR BINARY r.manifest_sha256<>BINARY d.manifest_sha256
 OR BINARY r.manifest_json<>BINARY CAST(d.manifest_json AS CHAR CHARACTER SET utf8mb4)
 OR r.stored_content_sha256<>SHA2(CAST(d.manifest_json AS CHAR CHARACTER SET utf8mb4),256)));
INSERT INTO compact_skill_download_guard SELECT NOT EXISTS(
 SELECT 1 FROM `__SOURCE_SCHEMA__`.agent_skill_storage_command c
 LEFT JOIN workflow_instance w ON w.kind='SKILL_STORAGE_COMMAND' AND w.legacy_source='agent_skill_storage_command' AND w.legacy_key=CAST(c.id AS CHAR)
 WHERE w.id IS NULL OR w.owner_user_id<>c.owner_user_id OR BINARY w.request_id<>BINARY c.request_id
 OR BINARY w.request_sha256<>BINARY c.request_sha256 OR BINARY w.resource_id<>BINARY c.download_id OR w.status<>c.status
 OR NOT(BINARY w.error_code<=>BINARY c.error_code) OR JSON_EXTRACT(w.payload_json,'$.removedBytes')<>c.removed_bytes
 OR JSON_EXTRACT(w.payload_json,'$.removedFiles')<>c.removed_files OR BINARY JSON_UNQUOTE(JSON_EXTRACT(w.payload_json,'$.downloadId'))<>BINARY c.download_id
 OR w.created_at<>CONVERT_TZ(c.created_at,'__SOURCE_SKILL_OFFSET__','+00:00') OR w.updated_at<>CONVERT_TZ(c.updated_at,'__SOURCE_SKILL_OFFSET__','+00:00'));
INSERT INTO compact_skill_download_guard SELECT NOT EXISTS(
 SELECT 1 FROM `__SOURCE_SCHEMA__`.agent_skill_download_event e
 LEFT JOIN audit_event a ON a.kind='SKILL_DOWNLOAD_EVENT' AND a.legacy_source='agent_skill_download_event' AND a.legacy_key=CAST(e.id AS CHAR)
 WHERE a.id IS NULL OR a.owner_user_id<>e.owner_user_id OR BINARY a.resource_id<>BINARY e.download_id OR a.action<>e.action
 OR JSON_UNQUOTE(JSON_EXTRACT(a.payload_json,'$.status'))<>e.status
 OR a.occurred_at<>CONVERT_TZ(e.created_at,'__SOURCE_SKILL_OFFSET__','+00:00'));
-- The resulting runtime relationship must retain the same owner at all three
-- endpoints: skill version, durable download request, and sealed package content.
INSERT INTO compact_skill_download_guard SELECT NOT EXISTS(
 SELECT 1 FROM content_revision v
 LEFT JOIN workflow_instance w ON w.kind='SKILL_DOWNLOAD' AND w.workflow_id=v.source_import_id AND w.owner_user_id=v.owner_user_id
 LEFT JOIN content_revision p ON p.asset_kind='SKILL_IMPORT' AND p.asset_id=v.source_import_id AND p.version=1 AND p.owner_user_id=v.owner_user_id
 WHERE v.asset_kind='SKILL' AND v.source_type='LINK' AND (w.id IS NULL OR p.id IS NULL
  OR w.status NOT IN ('DOWNLOADED','DRAFT_CREATED') OR p.source_type<>'LINK'
  OR p.manifest_json IS NULL OR p.manifest_sha256 IS NULL));
COMMIT;
DROP TEMPORARY TABLE compact_skill_download_guard;
