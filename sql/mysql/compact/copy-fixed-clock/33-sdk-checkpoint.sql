-- __SOURCE_SDK_OFFSET__ requires evidence for source updated_at DATETIME values.
-- Source writers must be stopped. Abort on first SQL error and ROLLBACK on this connection.
CREATE TEMPORARY TABLE compact_sdk_guard(valid INT NOT NULL CHECK(valid=1));
START TRANSACTION;
-- BEGIN reviewed fixed-offset conversion guards
INSERT INTO compact_sdk_guard SELECT IF(REGEXP_LIKE('__SOURCE_SDK_OFFSET__','^[+-][0-9]{2}:[0-9]{2}$','c') AND CONVERT_TZ('2026-01-01','__SOURCE_SDK_OFFSET__','+00:00') IS NOT NULL,1,0);
INSERT INTO compact_sdk_guard SELECT NOT EXISTS(SELECT 1 FROM `__SOURCE_SCHEMA__`.agent_workbench_sdk_state s WHERE (s.updated_at IS NOT NULL AND (CONVERT_TZ(s.updated_at,'__SOURCE_SDK_OFFSET__','+00:00') IS NULL OR NOT(TIMESTAMPDIFF(MICROSECOND,CONVERT_TZ(s.updated_at,'__SOURCE_SDK_OFFSET__','+00:00'),s.updated_at)<=>((IF(LEFT('__SOURCE_SDK_OFFSET__',1)='-',-1,1)*(CAST(SUBSTRING('__SOURCE_SDK_OFFSET__',2,2) AS SIGNED)*3600+CAST(SUBSTRING('__SOURCE_SDK_OFFSET__',5,2) AS SIGNED)*60))*1000000)))));
-- END reviewed fixed-offset conversion guards
INSERT INTO compact_sdk_guard SELECT IF(COUNT(*)=0,1,0) FROM runtime_state WHERE namespace='SDK_CHECKPOINT';
INSERT INTO compact_sdk_guard SELECT IF(CONVERT_TZ('2026-01-01 00:00:00','__SOURCE_SDK_OFFSET__','+00:00') IS NOT NULL,1,0);
INSERT INTO compact_sdk_guard SELECT IF(COUNT(*)=0,1,0) FROM `__SOURCE_SCHEMA__`.agent_workbench_owner WHERE user_id<=0;
INSERT INTO compact_sdk_guard SELECT IF(COUNT(*)=0,1,0) FROM `__SOURCE_SCHEMA__`.agent_workbench_sdk_state
 WHERE user_id NOT REGEXP '^[1-9][0-9]{0,18}$' OR CAST(user_id AS DECIMAL(20,0))>9223372036854775807
 OR revision<1 OR JSON_VALID(state_json)=0 OR CONVERT_TZ(updated_at,'__SOURCE_SDK_OFFSET__','+00:00') IS NULL;
INSERT INTO runtime_state(namespace,owner_id,scope_key,session_id,state_key,revision,state_code,payload_version,payload_json,created_at,updated_at)
 SELECT 'SDK_CHECKPOINT',CAST(user_id AS SIGNED),SHA2(CONCAT(OCTET_LENGTH(CONVERT(session_id USING utf8mb4)),':',session_id,':',OCTET_LENGTH(CONVERT(state_key USING utf8mb4)),':',state_key),256),
 session_id,state_key,revision,'LIVE',1,JSON_OBJECT('stateJson',state_json),NULL,CONVERT_TZ(updated_at,'__SOURCE_SDK_OFFSET__','+00:00')
 FROM `__SOURCE_SCHEMA__`.agent_workbench_sdk_state ORDER BY id;
-- The old mutex has no source timestamps; NULL created_at is intentional.
INSERT INTO runtime_state(namespace,owner_id,scope_key,revision,created_at)
 SELECT 'WORKBENCH',user_id,'',0,NULL FROM `__SOURCE_SCHEMA__`.agent_workbench_owner
 ON DUPLICATE KEY UPDATE namespace=runtime_state.namespace;
INSERT INTO compact_sdk_guard SELECT IF(
 (SELECT COUNT(*) FROM runtime_state WHERE namespace='SDK_CHECKPOINT')=(SELECT COUNT(*) FROM `__SOURCE_SCHEMA__`.agent_workbench_sdk_state),1,0);
INSERT INTO compact_sdk_guard SELECT IF(COUNT(*)=0,1,0)
 FROM `__SOURCE_SCHEMA__`.agent_workbench_sdk_state s LEFT JOIN runtime_state r
 ON r.namespace='SDK_CHECKPOINT' AND r.owner_id=CAST(s.user_id AS SIGNED) AND BINARY r.session_id=BINARY s.session_id AND BINARY r.state_key=BINARY s.state_key
 WHERE r.owner_id IS NULL OR r.revision<>s.revision OR NOT (BINARY JSON_UNQUOTE(JSON_EXTRACT(r.payload_json,'$.stateJson'))<=>BINARY s.state_json)
 OR BINARY r.scope_key<>BINARY SHA2(CONCAT(OCTET_LENGTH(CONVERT(s.session_id USING utf8mb4)),':',s.session_id,':',OCTET_LENGTH(CONVERT(s.state_key USING utf8mb4)),':',s.state_key),256)
 OR r.updated_at<>CONVERT_TZ(s.updated_at,'__SOURCE_SDK_OFFSET__','+00:00');
COMMIT;
DROP TEMPORARY TABLE compact_sdk_guard;
