-- Run AFTER agent_run copy. Render __SOURCE_AGENT_OFFSET__ from the same evidence as agent_run.
-- No event payload is reserialized, no sequence is renumbered. Source writers must be stopped.
-- Abort on first SQL error and ROLLBACK on this same connection.
CREATE TEMPORARY TABLE compact_journal_guard(valid INT NOT NULL CHECK(valid=1));
START TRANSACTION;
-- BEGIN reviewed fixed-offset conversion guards
INSERT INTO compact_journal_guard SELECT IF(REGEXP_LIKE('__SOURCE_AGENT_OFFSET__','^[+-][0-9]{2}:[0-9]{2}$','c') AND CONVERT_TZ('2026-01-01','__SOURCE_AGENT_OFFSET__','+00:00') IS NOT NULL,1,0);
INSERT INTO compact_journal_guard SELECT NOT EXISTS(SELECT 1 FROM `__SOURCE_SCHEMA__`.agent_run_event s WHERE (s.occurred_at IS NOT NULL AND (CONVERT_TZ(s.occurred_at,'__SOURCE_AGENT_OFFSET__','+00:00') IS NULL OR NOT(TIMESTAMPDIFF(MICROSECOND,CONVERT_TZ(s.occurred_at,'__SOURCE_AGENT_OFFSET__','+00:00'),s.occurred_at)<=>((IF(LEFT('__SOURCE_AGENT_OFFSET__',1)='-',-1,1)*(CAST(SUBSTRING('__SOURCE_AGENT_OFFSET__',2,2) AS SIGNED)*3600+CAST(SUBSTRING('__SOURCE_AGENT_OFFSET__',5,2) AS SIGNED)*60))*1000000)))));
-- END reviewed fixed-offset conversion guards
INSERT INTO compact_journal_guard SELECT IF(COUNT(*)=0,1,0) FROM audit_event WHERE kind='AGENT_RUN';
INSERT INTO compact_journal_guard SELECT IF(CONVERT_TZ('2026-01-01 00:00:00','__SOURCE_AGENT_OFFSET__','+00:00') IS NOT NULL,1,0);
INSERT INTO compact_journal_guard SELECT IF(COUNT(*)=0,1,0)
 FROM `__SOURCE_SCHEMA__`.agent_run_event e LEFT JOIN agent_run r ON BINARY r.run_id=BINARY e.run_id
 WHERE r.id IS NULL OR r.user_id<>e.user_id OR e.sequence_no<1 OR e.sequence_no>r.last_sequence
 OR JSON_VALID(e.payload_json)=0 OR JSON_TYPE(CAST(e.payload_json AS JSON))<>'OBJECT'
 OR CONVERT_TZ(e.occurred_at,'__SOURCE_AGENT_OFFSET__','+00:00') IS NULL;
INSERT INTO compact_journal_guard SELECT IF(COUNT(*)=0,1,0)
 FROM `__SOURCE_SCHEMA__`.agent_run r WHERE r.last_sequence<>(SELECT COUNT(*) FROM `__SOURCE_SCHEMA__`.agent_run_event e WHERE BINARY e.run_id=BINARY r.run_id);
INSERT INTO audit_event(event_id,kind,owner_user_id,run_id,journal_run_id,sequence_no,action,occurred_at,payload_version,payload_json,legacy_source,legacy_key)
 SELECT CONCAT('legacy-agent-run-',id),'AGENT_RUN',user_id,run_id,run_id,sequence_no,event_type,
 CONVERT_TZ(occurred_at,'__SOURCE_AGENT_OFFSET__','+00:00'),1,payload_json,'agent_run_event',CAST(id AS CHAR)
 FROM `__SOURCE_SCHEMA__`.agent_run_event ORDER BY id;
INSERT INTO compact_journal_guard SELECT IF(
 (SELECT COUNT(*) FROM audit_event WHERE kind='AGENT_RUN')=(SELECT COUNT(*) FROM `__SOURCE_SCHEMA__`.agent_run_event),1,0);
INSERT INTO compact_journal_guard SELECT IF(COUNT(*)=0,1,0)
 FROM `__SOURCE_SCHEMA__`.agent_run_event s LEFT JOIN audit_event e ON e.legacy_source='agent_run_event' AND e.legacy_key=CAST(s.id AS CHAR)
 WHERE e.id IS NULL OR e.owner_user_id<>s.user_id OR BINARY e.run_id<>BINARY s.run_id OR BINARY e.journal_run_id<>BINARY s.run_id
 OR e.sequence_no<>s.sequence_no OR BINARY e.action<>BINARY s.event_type OR BINARY e.payload_json<>BINARY s.payload_json
 OR e.occurred_at<>CONVERT_TZ(s.occurred_at,'__SOURCE_AGENT_OFFSET__','+00:00');
COMMIT;
DROP TEMPORARY TABLE compact_journal_guard;
