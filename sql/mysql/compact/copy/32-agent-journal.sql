-- Generated explicit legacy-clock protocol by author_legacy_clock_copy.py.
-- validation_wall_offset is ONLY a zero-shift wall-value validator when unresolved.
-- It is never persisted as a source offset or used to manufacture UTC.
SET @compact_source_clock_unresolved=BINARY '__SOURCE_AGENT_OFFSET__'=BINARY 'UNRESOLVED';
SET @compact_validation_wall_offset=IF(@compact_source_clock_unresolved,'+00:00','__SOURCE_AGENT_OFFSET__');
CREATE TEMPORARY TABLE compact_journal_guard(valid INT NOT NULL CHECK(valid=1));
START TRANSACTION;
INSERT INTO compact_journal_guard SELECT IF(NOT @compact_source_clock_unresolved OR REGEXP_LIKE('__SOURCE_SNAPSHOT_SHA256__','^[a-f0-9]{64}$','c'),1,0);
INSERT INTO compact_journal_guard SELECT IF(REGEXP_LIKE(@compact_validation_wall_offset,'^[+-][0-9]{2}:[0-9]{2}$','c') AND CONVERT_TZ('2026-01-01',@compact_validation_wall_offset,'+00:00') IS NOT NULL,1,0);
INSERT INTO compact_journal_guard SELECT NOT EXISTS(SELECT 1 FROM `__SOURCE_SCHEMA__`.agent_run_event s WHERE (s.occurred_at IS NOT NULL AND (CONVERT_TZ(s.occurred_at,@compact_validation_wall_offset,'+00:00') IS NULL OR NOT(TIMESTAMPDIFF(MICROSECOND,CONVERT_TZ(s.occurred_at,@compact_validation_wall_offset,'+00:00'),s.occurred_at)<=>((IF(LEFT(@compact_validation_wall_offset,1)='-',-1,1)*(CAST(SUBSTRING(@compact_validation_wall_offset,2,2) AS SIGNED)*3600+CAST(SUBSTRING(@compact_validation_wall_offset,5,2) AS SIGNED)*60))*1000000)))));
INSERT INTO compact_journal_guard SELECT IF(COUNT(*)=0,1,0) FROM audit_event WHERE kind='AGENT_RUN';
INSERT INTO compact_journal_guard SELECT IF(CONVERT_TZ('2026-01-01 00:00:00',@compact_validation_wall_offset,'+00:00') IS NOT NULL,1,0);
INSERT INTO compact_journal_guard SELECT IF(COUNT(*)=0,1,0)
 FROM `__SOURCE_SCHEMA__`.agent_run_event e LEFT JOIN agent_run r ON BINARY r.run_id=BINARY e.run_id
 WHERE r.id IS NULL OR r.user_id<>e.user_id OR e.sequence_no<1 OR e.sequence_no>r.last_sequence
 OR JSON_VALID(e.payload_json)=0 OR JSON_TYPE(CAST(e.payload_json AS JSON))<>'OBJECT'
 OR CONVERT_TZ(e.occurred_at,@compact_validation_wall_offset,'+00:00') IS NULL;
INSERT INTO compact_journal_guard SELECT IF(COUNT(*)=0,1,0)
 FROM `__SOURCE_SCHEMA__`.agent_run r WHERE r.last_sequence<>(SELECT COUNT(*) FROM `__SOURCE_SCHEMA__`.agent_run_event e WHERE BINARY e.run_id=BINARY r.run_id);
INSERT INTO audit_event(event_id,kind,owner_user_id,run_id,journal_run_id,sequence_no,action,occurred_at,payload_version,payload_json,legacy_source,legacy_key,legacy_clock_json) SELECT CONCAT('legacy-agent-run-',id),'AGENT_RUN',user_id,run_id,run_id,sequence_no,event_type,IF(@compact_source_clock_unresolved,NULL,CONVERT_TZ(occurred_at,@compact_validation_wall_offset,'+00:00')),1,payload_json,'agent_run_event',CAST(id AS CHAR),IF(@compact_source_clock_unresolved,JSON_OBJECT('protocol','doorhandle-legacy-clock-v1','status','UNRESOLVED','sourceTable','agent_run_event','sourceKey',JSON_OBJECT('id',agent_run_event.`id`),'sourceSnapshotSha256','__SOURCE_SNAPSHOT_SHA256__','sourceRowSha256',SHA2(CAST(JSON_OBJECT('id',agent_run_event.`id`,'run_id',agent_run_event.`run_id`,'user_id',agent_run_event.`user_id`,'sequence_no',agent_run_event.`sequence_no`,'event_type',agent_run_event.`event_type`,'occurred_at',CAST(agent_run_event.`occurred_at` AS CHAR CHARACTER SET utf8mb4),'payload_json',CAST(agent_run_event.`payload_json` AS CHAR CHARACTER SET utf8mb4)) AS CHAR CHARACTER SET utf8mb4),256),'sourceWallTimes',JSON_OBJECT('occurred_at',CAST(agent_run_event.`occurred_at` AS CHAR))),NULL) FROM `__SOURCE_SCHEMA__`.agent_run_event ORDER BY id;
INSERT INTO compact_journal_guard SELECT IF(
 (SELECT COUNT(*) FROM audit_event WHERE kind='AGENT_RUN')=(SELECT COUNT(*) FROM `__SOURCE_SCHEMA__`.agent_run_event),1,0);
INSERT INTO compact_journal_guard SELECT IF(COUNT(*)=0,1,0)
 FROM `__SOURCE_SCHEMA__`.agent_run_event s LEFT JOIN audit_event e ON e.legacy_source='agent_run_event' AND e.legacy_key=CAST(s.id AS CHAR)
 WHERE e.id IS NULL OR e.owner_user_id<>s.user_id OR BINARY e.run_id<>BINARY s.run_id OR BINARY e.journal_run_id<>BINARY s.run_id
 OR e.sequence_no<>s.sequence_no OR BINARY e.action<>BINARY s.event_type OR BINARY e.payload_json<>BINARY s.payload_json
 OR NOT(e.occurred_at<=>IF(@compact_source_clock_unresolved,NULL,CONVERT_TZ(s.occurred_at,@compact_validation_wall_offset,'+00:00')));
INSERT INTO compact_journal_guard SELECT IF(COUNT(*)=0,1,0) FROM `__SOURCE_SCHEMA__`.agent_run_event LEFT JOIN audit_event clock_target ON BINARY clock_target.`legacy_source`<=>BINARY 'agent_run_event' AND BINARY clock_target.`legacy_key`<=>BINARY CAST(id AS CHAR) WHERE (clock_target.id IS NULL OR NOT(clock_target.legacy_clock_json<=>IF(@compact_source_clock_unresolved,JSON_OBJECT('protocol','doorhandle-legacy-clock-v1','status','UNRESOLVED','sourceTable','agent_run_event','sourceKey',JSON_OBJECT('id',agent_run_event.`id`),'sourceSnapshotSha256','__SOURCE_SNAPSHOT_SHA256__','sourceRowSha256',SHA2(CAST(JSON_OBJECT('id',agent_run_event.`id`,'run_id',agent_run_event.`run_id`,'user_id',agent_run_event.`user_id`,'sequence_no',agent_run_event.`sequence_no`,'event_type',agent_run_event.`event_type`,'occurred_at',CAST(agent_run_event.`occurred_at` AS CHAR CHARACTER SET utf8mb4),'payload_json',CAST(agent_run_event.`payload_json` AS CHAR CHARACTER SET utf8mb4)) AS CHAR CHARACTER SET utf8mb4),256),'sourceWallTimes',JSON_OBJECT('occurred_at',CAST(agent_run_event.`occurred_at` AS CHAR))),NULL)) OR NOT(clock_target.`occurred_at`<=>IF(@compact_source_clock_unresolved,NULL,CONVERT_TZ(occurred_at,@compact_validation_wall_offset,'+00:00'))) OR NOT(BINARY clock_target.`payload_json`<=>BINARY payload_json));
COMMIT;
DROP TEMPORARY TABLE compact_journal_guard;
