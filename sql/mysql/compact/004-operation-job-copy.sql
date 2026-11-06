-- Requires 003-chat-aggregate-expand and 004-operation-job. Use one connection
-- on a stopped-writer clone; stop at the first error. Old fork receipts with a
-- deleted child are preserved in operation_job rather than silently skipped.
CREATE TEMPORARY TABLE compact_fork_copy_guard (valid TINYINT NOT NULL CHECK(valid=1));
START TRANSACTION;
INSERT INTO compact_fork_copy_guard(valid)
SELECT CASE WHEN NOT EXISTS (
    SELECT 1 FROM agent_session_fork f JOIN chat_session s ON s.session_id=f.fork_session_id
    WHERE s.user_id<>f.user_id OR (s.fork_request_id IS NOT NULL AND (
        s.fork_owner_user_id<>f.user_id OR BINARY s.fork_request_id<>BINARY f.request_id
        OR BINARY s.fork_source_session_id<>BINARY f.source_session_id OR s.fork_through_message_id<>f.through_message_id
        OR s.fork_legacy_id IS NULL OR s.fork_legacy_id<>f.id))
) AND NOT EXISTS (
    SELECT 1 FROM agent_session_fork f JOIN operation_job j
      ON (j.namespace='AGENT_WORKSPACE' AND j.job_kind='WORKSPACE_FORK' AND j.owner_user_id=f.user_id AND j.request_id=f.request_id)
      OR (j.legacy_source='agent_session_fork' AND j.legacy_id=f.id)
    WHERE j.namespace<>'AGENT_WORKSPACE' OR j.job_kind<>'WORKSPACE_FORK' OR j.owner_user_id<>f.user_id
       OR BINARY j.request_id<>BINARY f.request_id OR j.status<>'COMPLETED'
       OR BINARY j.source_session_id<>BINARY f.source_session_id OR j.through_message_id<>f.through_message_id
       OR BINARY j.result_session_id<>BINARY f.fork_session_id
       OR j.legacy_source IS NULL OR j.legacy_source<>'agent_session_fork' OR j.legacy_id IS NULL OR j.legacy_id<>f.id
) THEN 1 ELSE 0 END;

INSERT INTO operation_job(namespace,job_kind,owner_user_id,request_id,status,revision,
    source_session_id,through_message_id,result_session_id,legacy_source,legacy_id,created_at)
SELECT 'AGENT_WORKSPACE','WORKSPACE_FORK',f.user_id,f.request_id,'COMPLETED',0,
    f.source_session_id,f.through_message_id,f.fork_session_id,'agent_session_fork',f.id,NULL
FROM agent_session_fork f
ON DUPLICATE KEY UPDATE id=operation_job.id;
UPDATE chat_session s JOIN agent_session_fork f ON f.fork_session_id=s.session_id AND f.user_id=s.user_id
SET s.fork_owner_user_id=f.user_id,s.fork_request_id=f.request_id,s.fork_source_session_id=f.source_session_id,
    s.fork_through_message_id=f.through_message_id,s.fork_legacy_id=f.id
WHERE s.fork_request_id IS NULL;

INSERT INTO compact_fork_copy_guard(valid)
SELECT CASE WHEN
    (SELECT COUNT(*) FROM agent_session_fork)=(SELECT COUNT(*) FROM operation_job WHERE legacy_source='agent_session_fork')
    AND NOT EXISTS (
        SELECT 1 FROM agent_session_fork f JOIN chat_session s ON s.session_id=f.fork_session_id
        WHERE s.fork_legacy_id IS NULL OR s.fork_legacy_id<>f.id OR s.fork_owner_user_id<>f.user_id
            OR BINARY s.fork_request_id<>BINARY f.request_id OR BINARY s.fork_source_session_id<>BINARY f.source_session_id
            OR s.fork_through_message_id<>f.through_message_id
    ) THEN 1 ELSE 0 END;
COMMIT;
DROP TEMPORARY TABLE compact_fork_copy_guard;
