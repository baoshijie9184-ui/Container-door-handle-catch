-- Isolated ECS target only. Source schema and its observed Agent DATETIME offset
-- are explicit migration inputs. No source writes, seeds or default ownership.
CREATE TEMPORARY TABLE compact_run_guard(ok TINYINT NOT NULL CHECK(ok=1));
START TRANSACTION;
-- BEGIN reviewed fixed-offset conversion guards
INSERT INTO compact_run_guard SELECT IF(REGEXP_LIKE('__SOURCE_AGENT_OFFSET__','^[+-][0-9]{2}:[0-9]{2}$','c') AND CONVERT_TZ('2026-01-01','__SOURCE_AGENT_OFFSET__','+00:00') IS NOT NULL,1,0);
INSERT INTO compact_run_guard SELECT NOT EXISTS(SELECT 1 FROM `__SOURCE_SCHEMA__`.agent_run s WHERE (s.started_at IS NOT NULL AND (CONVERT_TZ(s.started_at,'__SOURCE_AGENT_OFFSET__','+00:00') IS NULL OR NOT(TIMESTAMPDIFF(MICROSECOND,CONVERT_TZ(s.started_at,'__SOURCE_AGENT_OFFSET__','+00:00'),s.started_at)<=>((IF(LEFT('__SOURCE_AGENT_OFFSET__',1)='-',-1,1)*(CAST(SUBSTRING('__SOURCE_AGENT_OFFSET__',2,2) AS UNSIGNED)*3600+CAST(SUBSTRING('__SOURCE_AGENT_OFFSET__',5,2) AS UNSIGNED)*60))*1000000)))) OR (s.ended_at IS NOT NULL AND (CONVERT_TZ(s.ended_at,'__SOURCE_AGENT_OFFSET__','+00:00') IS NULL OR NOT(TIMESTAMPDIFF(MICROSECOND,CONVERT_TZ(s.ended_at,'__SOURCE_AGENT_OFFSET__','+00:00'),s.ended_at)<=>((IF(LEFT('__SOURCE_AGENT_OFFSET__',1)='-',-1,1)*(CAST(SUBSTRING('__SOURCE_AGENT_OFFSET__',2,2) AS UNSIGNED)*3600+CAST(SUBSTRING('__SOURCE_AGENT_OFFSET__',5,2) AS UNSIGNED)*60))*1000000)))) OR (s.heartbeat_at IS NOT NULL AND (CONVERT_TZ(s.heartbeat_at,'__SOURCE_AGENT_OFFSET__','+00:00') IS NULL OR NOT(TIMESTAMPDIFF(MICROSECOND,CONVERT_TZ(s.heartbeat_at,'__SOURCE_AGENT_OFFSET__','+00:00'),s.heartbeat_at)<=>((IF(LEFT('__SOURCE_AGENT_OFFSET__',1)='-',-1,1)*(CAST(SUBSTRING('__SOURCE_AGENT_OFFSET__',2,2) AS UNSIGNED)*3600+CAST(SUBSTRING('__SOURCE_AGENT_OFFSET__',5,2) AS UNSIGNED)*60))*1000000)))) OR (s.lease_expires_at IS NOT NULL AND (CONVERT_TZ(s.lease_expires_at,'__SOURCE_AGENT_OFFSET__','+00:00') IS NULL OR NOT(TIMESTAMPDIFF(MICROSECOND,CONVERT_TZ(s.lease_expires_at,'__SOURCE_AGENT_OFFSET__','+00:00'),s.lease_expires_at)<=>((IF(LEFT('__SOURCE_AGENT_OFFSET__',1)='-',-1,1)*(CAST(SUBSTRING('__SOURCE_AGENT_OFFSET__',2,2) AS UNSIGNED)*3600+CAST(SUBSTRING('__SOURCE_AGENT_OFFSET__',5,2) AS UNSIGNED)*60))*1000000)))));
INSERT INTO compact_run_guard SELECT NOT EXISTS(SELECT 1 FROM `__SOURCE_SCHEMA__`.agent_research_answer s WHERE (s.recorded_at IS NOT NULL AND (CONVERT_TZ(s.recorded_at,'__SOURCE_AGENT_OFFSET__','+00:00') IS NULL OR NOT(TIMESTAMPDIFF(MICROSECOND,CONVERT_TZ(s.recorded_at,'__SOURCE_AGENT_OFFSET__','+00:00'),s.recorded_at)<=>((IF(LEFT('__SOURCE_AGENT_OFFSET__',1)='-',-1,1)*(CAST(SUBSTRING('__SOURCE_AGENT_OFFSET__',2,2) AS UNSIGNED)*3600+CAST(SUBSTRING('__SOURCE_AGENT_OFFSET__',5,2) AS UNSIGNED)*60))*1000000)))));
-- END reviewed fixed-offset conversion guards
INSERT INTO compact_run_guard SELECT NOT EXISTS(SELECT 1 FROM agent_run);
INSERT INTO compact_run_guard SELECT NOT EXISTS(
 SELECT 1 FROM `__SOURCE_SCHEMA__`.agent_research_answer a
 LEFT JOIN `__SOURCE_SCHEMA__`.agent_run r ON r.run_id=a.run_id AND r.user_id=a.user_id
 WHERE r.run_id IS NULL OR a.answer_sha256 IS NULL OR a.citations_json IS NULL OR a.unresolved_count<0
);
INSERT INTO compact_run_guard SELECT NOT EXISTS(
 SELECT 1 FROM `__SOURCE_SCHEMA__`.agent_run r
 WHERE CONVERT_TZ(r.started_at,'__SOURCE_AGENT_OFFSET__','+00:00') IS NULL
  OR CONVERT_TZ(r.heartbeat_at,'__SOURCE_AGENT_OFFSET__','+00:00') IS NULL
  OR CONVERT_TZ(r.lease_expires_at,'__SOURCE_AGENT_OFFSET__','+00:00') IS NULL
);

INSERT INTO agent_run(id,run_id,user_id,session_id,main_agent,entry_point,request_key,status,default_model,
 policy_version,instance_id,active_slot,last_sequence,started_at,ended_at,heartbeat_at,lease_expires_at,
 answer_owner_user_id,answer_sha256,answer_citations_json,answer_unresolved_count,answer_recorded_at,answer_legacy_id)
SELECT r.id,r.run_id,r.user_id,r.session_id,r.main_agent,r.entry_point,r.request_key,r.status,r.default_model,
 r.policy_version,r.instance_id,r.active_slot,r.last_sequence,
 CONVERT_TZ(r.started_at,'__SOURCE_AGENT_OFFSET__','+00:00'),
 CONVERT_TZ(r.ended_at,'__SOURCE_AGENT_OFFSET__','+00:00'),
 CONVERT_TZ(r.heartbeat_at,'__SOURCE_AGENT_OFFSET__','+00:00'),
 CONVERT_TZ(r.lease_expires_at,'__SOURCE_AGENT_OFFSET__','+00:00'),
 a.user_id,a.answer_sha256,a.citations_json,a.unresolved_count,
 CONVERT_TZ(a.recorded_at,'__SOURCE_AGENT_OFFSET__','+00:00'),a.id
FROM `__SOURCE_SCHEMA__`.agent_run r
LEFT JOIN `__SOURCE_SCHEMA__`.agent_research_answer a ON a.run_id=r.run_id AND a.user_id=r.user_id;

INSERT INTO compact_run_guard SELECT
 (SELECT COUNT(*) FROM agent_run)=(SELECT COUNT(*) FROM `__SOURCE_SCHEMA__`.agent_run)
 AND (SELECT COUNT(*) FROM agent_run WHERE answer_legacy_id IS NOT NULL)=
     (SELECT COUNT(*) FROM `__SOURCE_SCHEMA__`.agent_research_answer);

INSERT INTO compact_run_guard SELECT NOT EXISTS(
 SELECT 1 FROM `__SOURCE_SCHEMA__`.agent_run s LEFT JOIN agent_run t ON t.run_id=s.run_id
 WHERE t.run_id IS NULL OR NOT(t.id<=>s.id) OR NOT(t.user_id<=>s.user_id)
  OR NOT(BINARY t.session_id<=>BINARY s.session_id) OR NOT(BINARY t.main_agent<=>BINARY s.main_agent)
  OR NOT(BINARY t.entry_point<=>BINARY s.entry_point) OR NOT(BINARY t.request_key<=>BINARY s.request_key)
  OR NOT(BINARY t.status<=>BINARY s.status) OR NOT(BINARY t.default_model<=>BINARY s.default_model)
  OR NOT(BINARY t.policy_version<=>BINARY s.policy_version) OR NOT(BINARY t.instance_id<=>BINARY s.instance_id)
  OR NOT(t.active_slot<=>s.active_slot) OR NOT(t.last_sequence<=>s.last_sequence)
  OR NOT(t.started_at<=>CONVERT_TZ(s.started_at,'__SOURCE_AGENT_OFFSET__','+00:00'))
  OR NOT(t.ended_at<=>CONVERT_TZ(s.ended_at,'__SOURCE_AGENT_OFFSET__','+00:00'))
  OR NOT(t.heartbeat_at<=>CONVERT_TZ(s.heartbeat_at,'__SOURCE_AGENT_OFFSET__','+00:00'))
  OR NOT(t.lease_expires_at<=>CONVERT_TZ(s.lease_expires_at,'__SOURCE_AGENT_OFFSET__','+00:00'))
);
INSERT INTO compact_run_guard SELECT NOT EXISTS(
 SELECT 1 FROM `__SOURCE_SCHEMA__`.agent_research_answer a LEFT JOIN agent_run r ON r.run_id=a.run_id
 WHERE r.run_id IS NULL OR NOT(r.answer_legacy_id<=>a.id) OR NOT(r.answer_owner_user_id<=>a.user_id)
  OR NOT(BINARY r.answer_sha256<=>BINARY a.answer_sha256)
  OR NOT(BINARY CAST(r.answer_citations_json AS CHAR)<=>BINARY CAST(a.citations_json AS CHAR))
  OR NOT(r.answer_unresolved_count<=>a.unresolved_count)
  OR NOT(r.answer_recorded_at<=>CONVERT_TZ(a.recorded_at,'__SOURCE_AGENT_OFFSET__','+00:00'))
);
COMMIT;
DROP TEMPORARY TABLE compact_run_guard;
