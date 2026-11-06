-- Same stopped-writer clone as the expansion, using one stop-on-error session.
-- Temporary assertions fail the transaction rather than dropping orphaned or
-- conflicting source rows. No original content, IDs or timestamps are guessed.
CREATE TEMPORARY TABLE compact_research_guard (valid TINYINT NOT NULL CHECK(valid=1));
START TRANSACTION;
INSERT INTO compact_research_guard(valid)
SELECT CASE WHEN NOT EXISTS (
    SELECT 1 FROM agent_research_answer a LEFT JOIN agent_run r ON r.run_id=a.run_id
    WHERE r.run_id IS NULL OR r.user_id<>a.user_id OR a.unresolved_count<0
       OR (r.answer_sha256 IS NOT NULL AND (
           NOT(r.answer_owner_user_id <=> a.user_id) OR NOT(BINARY r.answer_sha256 <=> BINARY a.answer_sha256)
           OR NOT(r.answer_citations_json <=> a.citations_json)
           OR NOT(r.answer_unresolved_count <=> a.unresolved_count)
           OR NOT(r.answer_recorded_at <=> a.recorded_at) OR NOT(r.answer_legacy_id <=> a.id)))
) AND NOT EXISTS (SELECT run_id FROM agent_research_answer GROUP BY run_id HAVING COUNT(*)>1)
THEN 1 ELSE 0 END;
INSERT INTO compact_research_guard(valid)
SELECT CASE WHEN NOT EXISTS (
    SELECT 1 FROM agent_research_content_purge p LEFT JOIN agent_research_source s ON s.source_id=p.source_id
    WHERE s.source_id IS NULL OR s.user_id<>p.user_id OR p.cleared_chars<0
       OR (s.purged_at IS NOT NULL AND (
           NOT(s.purge_owner_user_id <=> p.user_id) OR NOT(s.cleared_chars <=> p.cleared_chars)
           OR NOT(s.purged_at <=> p.purged_at)))
) THEN 1 ELSE 0 END;

UPDATE agent_run r JOIN agent_research_answer a ON a.run_id=r.run_id AND a.user_id=r.user_id
SET r.answer_owner_user_id=a.user_id,r.answer_sha256=a.answer_sha256,
    r.answer_citations_json=a.citations_json,r.answer_unresolved_count=a.unresolved_count,
    r.answer_recorded_at=a.recorded_at,r.answer_legacy_id=a.id
WHERE r.answer_sha256 IS NULL;
UPDATE agent_research_source s JOIN agent_research_content_purge p
    ON p.source_id=s.source_id AND p.user_id=s.user_id
SET s.purge_owner_user_id=p.user_id,s.cleared_chars=p.cleared_chars,s.purged_at=p.purged_at
WHERE s.purged_at IS NULL;

INSERT INTO compact_research_guard(valid)
SELECT CASE WHEN NOT EXISTS (
    SELECT 1 FROM agent_research_answer a LEFT JOIN agent_run r ON r.run_id=a.run_id AND r.user_id=a.user_id
    WHERE r.run_id IS NULL OR NOT(r.answer_owner_user_id <=> a.user_id)
        OR NOT(BINARY r.answer_sha256 <=> BINARY a.answer_sha256)
        OR NOT(r.answer_citations_json <=> a.citations_json)
        OR NOT(r.answer_unresolved_count <=> a.unresolved_count)
        OR NOT(r.answer_recorded_at <=> a.recorded_at) OR NOT(r.answer_legacy_id <=> a.id)
) AND (SELECT COUNT(*) FROM agent_research_answer)=(SELECT COUNT(*) FROM agent_run WHERE answer_legacy_id IS NOT NULL)
AND NOT EXISTS (
    SELECT 1 FROM agent_research_content_purge p LEFT JOIN agent_research_source s ON s.source_id=p.source_id
    WHERE s.source_id IS NULL OR NOT(s.purge_owner_user_id <=> p.user_id)
        OR NOT(s.cleared_chars <=> p.cleared_chars) OR NOT(s.purged_at <=> p.purged_at)
) THEN 1 ELSE 0 END;
COMMIT;
DROP TEMPORARY TABLE compact_research_guard;
