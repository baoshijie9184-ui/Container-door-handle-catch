-- Render __SOURCE_SCHEMA__ as a validated MySQL identifier; USE the EMPTY target schema.
-- The runner must stop on first SQL error and ROLLBACK on that same connection.
-- Source writers must be stopped. Includes registered workflow receipts, events and owner locks.
CREATE TEMPORARY TABLE compact_knowledge_guard(valid INT NOT NULL CHECK(valid=1));
START TRANSACTION;
INSERT INTO compact_knowledge_guard SELECT IF(COUNT(*)=0,1,0) FROM content_asset WHERE asset_kind='KNOWLEDGE';
INSERT INTO compact_knowledge_guard SELECT IF(COUNT(*)=0,1,0) FROM workflow_instance WHERE kind='KNOWLEDGE_COMMAND';
INSERT INTO compact_knowledge_guard SELECT IF(COUNT(*)=0,1,0) FROM audit_event WHERE kind='KNOWLEDGE';
INSERT INTO compact_knowledge_guard SELECT IF(COUNT(*)=0,1,0) FROM
 (SELECT actor_user_id,request_id COLLATE utf8mb4_0900_ai_ci AS request_key FROM `__SOURCE_SCHEMA__`.quality_knowledge_command
 GROUP BY actor_user_id,request_id COLLATE utf8mb4_0900_ai_ci HAVING COUNT(*)>1) duplicate_requests;
INSERT INTO compact_knowledge_guard SELECT IF(COUNT(*)=0,1,0)
 FROM `__SOURCE_SCHEMA__`.quality_knowledge_command c JOIN `__SOURCE_SCHEMA__`.quality_knowledge_document d ON d.document_id=c.document_id
 WHERE BINARY d.document_id<>BINARY c.document_id;
INSERT INTO compact_knowledge_guard SELECT IF(COUNT(*)=0,1,0)
 FROM `__SOURCE_SCHEMA__`.quality_knowledge_audit e JOIN `__SOURCE_SCHEMA__`.quality_knowledge_document d ON d.document_id=e.document_id
 WHERE BINARY d.document_id<>BINARY e.document_id;
INSERT INTO compact_knowledge_guard
 SELECT IF(COUNT(*)=0,1,0) FROM `__SOURCE_SCHEMA__`.quality_knowledge_revision r
 LEFT JOIN `__SOURCE_SCHEMA__`.quality_knowledge_document d ON d.document_id=r.document_id
 WHERE d.document_id IS NULL OR BINARY d.document_id<>BINARY r.document_id OR r.version<1
 OR r.byte_length<>OCTET_LENGTH(r.source_bytes) OR BINARY r.source_sha256<>BINARY SHA2(r.source_bytes,256)
 OR BINARY r.content_sha256<>BINARY SHA2(CONVERT(r.content_text USING utf8mb4),256);
INSERT INTO compact_knowledge_guard
 SELECT IF(COUNT(*)=0,1,0) FROM `__SOURCE_SCHEMA__`.quality_knowledge_document d
 LEFT JOIN `__SOURCE_SCHEMA__`.quality_knowledge_revision r ON r.document_id=d.document_id AND r.version=d.current_version
 WHERE r.id IS NULL OR d.current_version<1 OR d.revision<0;
INSERT INTO compact_knowledge_guard
 SELECT IF(COUNT(*)=0,1,0) FROM `__SOURCE_SCHEMA__`.quality_knowledge_chunk c
 LEFT JOIN `__SOURCE_SCHEMA__`.quality_knowledge_revision r ON r.document_id=c.document_id AND r.version=c.version
 WHERE r.id IS NULL OR BINARY r.document_id<>BINARY c.document_id OR c.ordinal_no<1;
INSERT INTO compact_knowledge_guard
 SELECT IF(COUNT(*)=0,1,0) FROM `__SOURCE_SCHEMA__`.quality_knowledge_revision r
 WHERE r.chunk_count<>(SELECT COUNT(*) FROM `__SOURCE_SCHEMA__`.quality_knowledge_chunk c WHERE c.document_id=r.document_id AND c.version=r.version);

INSERT INTO content_asset(asset_id,asset_kind,owner_user_id,title,filename,visibility,lifecycle,current_version,revision,created_at,updated_at,legacy_source,legacy_id)
 SELECT document_id,'KNOWLEDGE',owner_user_id,title,filename,visibility,'PREPARING',NULL,revision,created_at,updated_at,'quality_knowledge_document',id
 FROM `__SOURCE_SCHEMA__`.quality_knowledge_document ORDER BY id;
INSERT INTO content_revision(asset_id,asset_kind,version,owner_user_id,creator_user_id,title,filename,content_text,content_sha256,stored_content_sha256,source_bytes,source_sha256,byte_length,media_type,index_state,chunk_count,created_at,legacy_source,legacy_id)
 SELECT r.document_id,'KNOWLEDGE',r.version,d.owner_user_id,r.creator_user_id,r.title,r.filename,r.content_text,r.content_sha256,r.content_sha256,r.source_bytes,r.source_sha256,r.byte_length,r.media_type,r.index_state,r.chunk_count,r.created_at,'quality_knowledge_revision',r.id
 FROM `__SOURCE_SCHEMA__`.quality_knowledge_revision r JOIN `__SOURCE_SCHEMA__`.quality_knowledge_document d ON d.document_id=r.document_id ORDER BY r.id;
INSERT INTO content_chunk(asset_id,version,ordinal_no,locator,content_text,legacy_source,legacy_id)
 SELECT document_id,version,ordinal_no,locator,content_text,'quality_knowledge_chunk',id
 FROM `__SOURCE_SCHEMA__`.quality_knowledge_chunk ORDER BY id;
UPDATE content_asset a JOIN `__SOURCE_SCHEMA__`.quality_knowledge_document d ON BINARY a.asset_id=BINARY d.document_id
 SET a.current_version=d.current_version,a.lifecycle=d.lifecycle WHERE a.asset_kind='KNOWLEDGE';

INSERT INTO workflow_instance(workflow_id,kind,idempotency_scope,request_id,request_sha256,owner_user_id,actor_user_id,resource_type,resource_id,resource_revision,status,revision,payload_version,payload_json,created_at,updated_at,finished_at,legacy_source,legacy_key)
 SELECT SHA2(CONCAT('KNOWLEDGE_COMMAND:',actor_user_id,':',request_id),256),'KNOWLEDGE_COMMAND',CONCAT('OWNER:',actor_user_id),request_id,request_sha256,actor_user_id,actor_user_id,'KNOWLEDGE',document_id,version,'COMPLETED',0,1,
 JSON_OBJECT('documentId',document_id,'documentVersion',version,'action',action_name),created_at,created_at,created_at,'quality_knowledge_command',CAST(JSON_ARRAY(actor_user_id,request_id) AS CHAR)
 FROM `__SOURCE_SCHEMA__`.quality_knowledge_command ORDER BY actor_user_id,request_id;
INSERT INTO audit_event(event_id,kind,owner_user_id,actor_user_id,resource_type,resource_id,action,revision,content_sha256,occurred_at,payload_version,payload_json,legacy_source,legacy_key)
 SELECT CONCAT('legacy-knowledge-',e.id),'KNOWLEDGE',d.owner_user_id,e.actor_user_id,'KNOWLEDGE',e.document_id,e.action_name,e.version,e.content_sha256,e.created_at,1,
 JSON_OBJECT('documentId',e.document_id,'documentVersion',e.version,'action',e.action_name),'quality_knowledge_audit',CAST(e.id AS CHAR)
 FROM `__SOURCE_SCHEMA__`.quality_knowledge_audit e LEFT JOIN `__SOURCE_SCHEMA__`.quality_knowledge_document d ON d.document_id=e.document_id ORDER BY e.id;
-- The source lock row has no timestamp. NULL records that fact; updated_at is target-write metadata.
INSERT INTO runtime_state(namespace,owner_id,scope_key,revision,created_at)
 SELECT 'KNOWLEDGE',owner_user_id,'',0,NULL FROM `__SOURCE_SCHEMA__`.quality_knowledge_owner
 ON DUPLICATE KEY UPDATE namespace=runtime_state.namespace;

INSERT INTO compact_knowledge_guard SELECT IF(
 (SELECT COUNT(*) FROM content_asset WHERE asset_kind='KNOWLEDGE')=(SELECT COUNT(*) FROM `__SOURCE_SCHEMA__`.quality_knowledge_document)
 AND (SELECT COUNT(*) FROM content_revision WHERE asset_kind='KNOWLEDGE')=(SELECT COUNT(*) FROM `__SOURCE_SCHEMA__`.quality_knowledge_revision)
 AND (SELECT COUNT(*) FROM content_chunk WHERE legacy_source='quality_knowledge_chunk')=(SELECT COUNT(*) FROM `__SOURCE_SCHEMA__`.quality_knowledge_chunk),1,0);
INSERT INTO compact_knowledge_guard
 SELECT IF(COUNT(*)=0,1,0) FROM `__SOURCE_SCHEMA__`.quality_knowledge_revision s
 LEFT JOIN content_revision t ON t.legacy_source='quality_knowledge_revision' AND t.legacy_id=s.id
 WHERE t.id IS NULL OR NOT(BINARY t.content_text<=>BINARY s.content_text) OR NOT(t.source_bytes<=>s.source_bytes)
 OR NOT(BINARY t.content_sha256<=>BINARY s.content_sha256) OR NOT(BINARY t.source_sha256<=>BINARY s.source_sha256)
 OR NOT(t.created_at<=>s.created_at) OR NOT(t.creator_user_id<=>s.creator_user_id);
INSERT INTO compact_knowledge_guard SELECT IF(
 (SELECT COUNT(*) FROM workflow_instance WHERE kind='KNOWLEDGE_COMMAND')=(SELECT COUNT(*) FROM `__SOURCE_SCHEMA__`.quality_knowledge_command)
 AND (SELECT COUNT(*) FROM audit_event WHERE kind='KNOWLEDGE')=(SELECT COUNT(*) FROM `__SOURCE_SCHEMA__`.quality_knowledge_audit),1,0);
INSERT INTO compact_knowledge_guard SELECT IF(COUNT(*)=0,1,0)
 FROM `__SOURCE_SCHEMA__`.quality_knowledge_command s
 LEFT JOIN workflow_instance t ON t.kind='KNOWLEDGE_COMMAND' AND t.idempotency_scope=CONCAT('OWNER:',s.actor_user_id) AND BINARY t.request_id=BINARY s.request_id
 WHERE t.id IS NULL OR NOT(BINARY t.request_sha256<=>BINARY s.request_sha256) OR NOT(BINARY t.resource_id<=>BINARY s.document_id)
 OR NOT(t.resource_revision<=>s.version) OR NOT(t.created_at<=>s.created_at);
COMMIT;
DROP TEMPORARY TABLE compact_knowledge_guard;
