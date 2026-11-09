-- Isolated ECS target only, after agent_run copy and before application writers.
-- A migration runner must validate and replace the source schema identifier and
-- the observed source research DATETIME offset. Do not guess it from host time.
-- Original fetched-body hashes are not hashes of the stored scrubbed excerpts.
CREATE TEMPORARY TABLE compact_research_guard (
 ok TINYINT NOT NULL CHECK (ok=1)
);
START TRANSACTION;
-- BEGIN reviewed fixed-offset conversion guards
INSERT INTO compact_research_guard SELECT IF(REGEXP_LIKE('__SOURCE_RESEARCH_OFFSET__','^[+-][0-9]{2}:[0-9]{2}$','c') AND CONVERT_TZ('2026-01-01','__SOURCE_RESEARCH_OFFSET__','+00:00') IS NOT NULL,1,0);
INSERT INTO compact_research_guard SELECT NOT EXISTS(SELECT 1 FROM `__SOURCE_SCHEMA__`.agent_research_source s WHERE (s.fetched_at IS NOT NULL AND (CONVERT_TZ(s.fetched_at,'__SOURCE_RESEARCH_OFFSET__','+00:00') IS NULL OR NOT(TIMESTAMPDIFF(MICROSECOND,CONVERT_TZ(s.fetched_at,'__SOURCE_RESEARCH_OFFSET__','+00:00'),s.fetched_at)<=>((IF(LEFT('__SOURCE_RESEARCH_OFFSET__',1)='-',-1,1)*(CAST(SUBSTRING('__SOURCE_RESEARCH_OFFSET__',2,2) AS SIGNED)*3600+CAST(SUBSTRING('__SOURCE_RESEARCH_OFFSET__',5,2) AS SIGNED)*60))*1000000)))) OR (s.expires_at IS NOT NULL AND (CONVERT_TZ(s.expires_at,'__SOURCE_RESEARCH_OFFSET__','+00:00') IS NULL OR NOT(TIMESTAMPDIFF(MICROSECOND,CONVERT_TZ(s.expires_at,'__SOURCE_RESEARCH_OFFSET__','+00:00'),s.expires_at)<=>((IF(LEFT('__SOURCE_RESEARCH_OFFSET__',1)='-',-1,1)*(CAST(SUBSTRING('__SOURCE_RESEARCH_OFFSET__',2,2) AS SIGNED)*3600+CAST(SUBSTRING('__SOURCE_RESEARCH_OFFSET__',5,2) AS SIGNED)*60))*1000000)))));
INSERT INTO compact_research_guard SELECT NOT EXISTS(SELECT 1 FROM `__SOURCE_SCHEMA__`.agent_research_content_purge s WHERE (s.purged_at IS NOT NULL AND (CONVERT_TZ(s.purged_at,'__SOURCE_RESEARCH_OFFSET__','+00:00') IS NULL OR NOT(TIMESTAMPDIFF(MICROSECOND,CONVERT_TZ(s.purged_at,'__SOURCE_RESEARCH_OFFSET__','+00:00'),s.purged_at)<=>((IF(LEFT('__SOURCE_RESEARCH_OFFSET__',1)='-',-1,1)*(CAST(SUBSTRING('__SOURCE_RESEARCH_OFFSET__',2,2) AS SIGNED)*3600+CAST(SUBSTRING('__SOURCE_RESEARCH_OFFSET__',5,2) AS SIGNED)*60))*1000000)))));
-- END reviewed fixed-offset conversion guards

INSERT INTO compact_research_guard SELECT
 NOT EXISTS(SELECT 1 FROM content_asset WHERE asset_kind='RESEARCH_SOURCE')
 AND NOT EXISTS(SELECT 1 FROM content_revision WHERE asset_kind='RESEARCH_SOURCE')
 AND NOT EXISTS(SELECT 1 FROM content_link WHERE link_kind='RESEARCH_SOURCE');

-- An orphan or owner mismatch is an error, never an implicitly filtered row.
INSERT INTO compact_research_guard SELECT NOT EXISTS(
 SELECT 1 FROM `__SOURCE_SCHEMA__`.agent_research_source s
 LEFT JOIN agent_run r ON r.run_id=s.run_id AND r.user_id=s.user_id
 WHERE r.run_id IS NULL OR s.user_id<=0 OR s.content_sha256 IS NULL OR s.request_sha256 IS NULL
  OR CONVERT_TZ(s.fetched_at,'__SOURCE_RESEARCH_OFFSET__','+00:00') IS NULL
  OR CONVERT_TZ(s.expires_at,'__SOURCE_RESEARCH_OFFSET__','+00:00') IS NULL
);
INSERT INTO compact_research_guard SELECT NOT EXISTS(
 SELECT 1 FROM `__SOURCE_SCHEMA__`.agent_research_content_purge p
 LEFT JOIN `__SOURCE_SCHEMA__`.agent_research_source s ON s.source_id=p.source_id AND s.user_id=p.user_id
 WHERE s.source_id IS NULL OR p.cleared_chars<0 OR p.purged_at IS NULL
  OR s.requested_url<>'' OR s.title<>'' OR s.excerpt<>''
);

INSERT INTO content_asset(asset_id,asset_kind,owner_user_id,title,visibility,lifecycle,current_version,
 revision,created_at,updated_at,legacy_source,legacy_id)
SELECT s.source_id,'RESEARCH_SOURCE',s.user_id,s.title,'PRIVATE','PREPARING',NULL,1,
 CONVERT_TZ(s.fetched_at,'__SOURCE_RESEARCH_OFFSET__','+00:00'),
 CONVERT_TZ(s.fetched_at,'__SOURCE_RESEARCH_OFFSET__','+00:00'),'agent_research_source',s.id
FROM `__SOURCE_SCHEMA__`.agent_research_source s;

INSERT INTO content_revision(asset_id,asset_kind,version,owner_user_id,creator_user_id,title,content_text,
 content_sha256,stored_content_sha256,source_sha256,byte_length,media_type,content_state,
 source_run_id,source_url,source_query_omitted,source_url_redacted,range_start,max_length,text_chars,
 request_sha256,expires_at,purge_owner_user_id,cleared_chars,purged_at,created_at,legacy_source,legacy_id)
SELECT s.source_id,'RESEARCH_SOURCE',1,s.user_id,s.user_id,s.title,s.excerpt,
 s.content_sha256,CASE WHEN p.source_id IS NULL THEN SHA2(s.excerpt,256) ELSE NULL END,
 s.content_sha256,CASE WHEN p.source_id IS NULL THEN OCTET_LENGTH(s.excerpt) ELSE NULL END,'text/plain; charset=utf-8',
 CASE WHEN p.source_id IS NULL THEN 'PRESENT' ELSE 'PURGED' END,
 s.run_id,s.requested_url,s.query_omitted,s.url_redacted,s.start_index,s.max_length,s.text_chars,
 s.request_sha256,CONVERT_TZ(s.expires_at,'__SOURCE_RESEARCH_OFFSET__','+00:00'),
 p.user_id,p.cleared_chars,CONVERT_TZ(p.purged_at,'__SOURCE_RESEARCH_OFFSET__','+00:00'),
 CONVERT_TZ(s.fetched_at,'__SOURCE_RESEARCH_OFFSET__','+00:00'),'agent_research_source',s.id
FROM `__SOURCE_SCHEMA__`.agent_research_source s
LEFT JOIN `__SOURCE_SCHEMA__`.agent_research_content_purge p ON p.source_id=s.source_id AND p.user_id=s.user_id;

INSERT INTO content_link(link_kind,owner_user_id,run_id,call_id,asset_id,asset_version,request_sha256,state,
 created_at,legacy_source,legacy_id)
SELECT 'RESEARCH_SOURCE',s.user_id,s.run_id,s.call_id,s.source_id,1,s.request_sha256,'ACTIVE',
 CONVERT_TZ(s.fetched_at,'__SOURCE_RESEARCH_OFFSET__','+00:00'),'agent_research_source',s.id
FROM `__SOURCE_SCHEMA__`.agent_research_source s;

UPDATE content_asset SET current_version=1,lifecycle='ACTIVE' WHERE asset_kind='RESEARCH_SOURCE';

INSERT INTO compact_research_guard SELECT
 (SELECT COUNT(*) FROM `__SOURCE_SCHEMA__`.agent_research_source)=
 (SELECT COUNT(*) FROM content_asset WHERE asset_kind='RESEARCH_SOURCE')
 AND (SELECT COUNT(*) FROM `__SOURCE_SCHEMA__`.agent_research_source)=
 (SELECT COUNT(*) FROM content_revision WHERE asset_kind='RESEARCH_SOURCE')
 AND (SELECT COUNT(*) FROM `__SOURCE_SCHEMA__`.agent_research_source)=
 (SELECT COUNT(*) FROM content_link WHERE link_kind='RESEARCH_SOURCE');

INSERT INTO compact_research_guard SELECT NOT EXISTS(
 SELECT 1 FROM `__SOURCE_SCHEMA__`.agent_research_source s
 LEFT JOIN content_asset a ON a.asset_id=s.source_id AND a.asset_kind='RESEARCH_SOURCE'
 LEFT JOIN content_revision r ON r.asset_id=s.source_id AND r.version=1 AND r.asset_kind='RESEARCH_SOURCE'
 LEFT JOIN content_link l ON l.asset_id=s.source_id AND l.link_kind='RESEARCH_SOURCE'
 WHERE a.asset_id IS NULL OR r.asset_id IS NULL OR l.asset_id IS NULL
  OR NOT(a.owner_user_id<=>s.user_id) OR NOT(r.owner_user_id<=>s.user_id) OR NOT(l.owner_user_id<=>s.user_id)
  OR NOT(l.run_id<=>s.run_id) OR NOT(l.call_id<=>s.call_id) OR NOT(l.request_sha256<=>s.request_sha256)
  OR NOT(r.source_sha256<=>s.content_sha256) OR NOT(r.content_sha256<=>s.content_sha256)
  OR NOT(BINARY r.source_url<=>BINARY s.requested_url) OR NOT(BINARY r.title<=>BINARY s.title)
  OR NOT(BINARY r.content_text<=>BINARY s.excerpt)
  OR NOT(r.source_query_omitted<=>s.query_omitted) OR NOT(r.source_url_redacted<=>s.url_redacted)
  OR NOT(r.range_start<=>s.start_index) OR NOT(r.max_length<=>s.max_length) OR NOT(r.text_chars<=>s.text_chars)
  OR NOT(r.created_at<=>CONVERT_TZ(s.fetched_at,'__SOURCE_RESEARCH_OFFSET__','+00:00'))
  OR NOT(r.expires_at<=>CONVERT_TZ(s.expires_at,'__SOURCE_RESEARCH_OFFSET__','+00:00'))
);
INSERT INTO compact_research_guard SELECT NOT EXISTS(
 SELECT 1 FROM `__SOURCE_SCHEMA__`.agent_research_content_purge p
 LEFT JOIN content_revision r ON r.asset_id=p.source_id AND r.asset_kind='RESEARCH_SOURCE' AND r.version=1
 WHERE r.asset_id IS NULL OR r.content_state<>'PURGED' OR NOT(r.purge_owner_user_id<=>p.user_id)
  OR NOT(r.cleared_chars<=>p.cleared_chars)
  OR NOT(r.purged_at<=>CONVERT_TZ(p.purged_at,'__SOURCE_RESEARCH_OFFSET__','+00:00'))
);
COMMIT;
DROP TEMPORARY TABLE compact_research_guard;
