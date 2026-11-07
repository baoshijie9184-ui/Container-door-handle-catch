CREATE TRIGGER compact_legacy_chat_projection_insert
BEFORE INSERT ON chat_message FOR EACH ROW
BEGIN
    IF NEW.execution_run_id IS NOT NULL AND (NEW.execution_created_at IS NULL OR EXISTS(SELECT 1 FROM audit_event e WHERE e.id=NEW.execution_evidence_id AND e.legacy_clock_json IS NOT NULL)) THEN
        IF NEW.execution_created_at IS NOT NULL OR NEW.execution_legacy_id IS NULL OR NOT EXISTS(SELECT 1 FROM audit_event e WHERE e.id=NEW.execution_evidence_id AND e.owner_user_id=NEW.execution_owner_user_id AND e.kind='MESSAGE_EXECUTION' AND e.legacy_source='agent_message_execution' AND e.message_id=NEW.id AND BINARY NEW.role=BINARY 'assistant' AND BINARY e.session_id=BINARY NEW.session_id AND BINARY e.legacy_key=BINARY CAST(NEW.execution_legacy_id AS CHAR) AND e.occurred_at IS NULL AND e.legacy_clock_json IS NOT NULL AND BINARY JSON_UNQUOTE(JSON_EXTRACT(e.legacy_clock_json,'$.sourceTable'))=BINARY 'agent_message_execution' AND CAST(JSON_UNQUOTE(JSON_EXTRACT(e.legacy_clock_json,'$.sourceKey.id')) AS DECIMAL(20,0))=NEW.execution_legacy_id AND BINARY e.run_id=BINARY NEW.execution_run_id) THEN
            SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Unknown chat projection requires its exact original audit clock evidence';
        END IF;
    END IF;
    IF NEW.snapshot_evidence_id IS NOT NULL AND (NEW.workspace_snapshot_created_at IS NULL OR EXISTS(SELECT 1 FROM audit_event e WHERE e.id=NEW.snapshot_evidence_id AND e.legacy_clock_json IS NOT NULL)) THEN
        IF NEW.workspace_snapshot_created_at IS NOT NULL OR NEW.workspace_snapshot_legacy_id IS NULL OR NOT EXISTS(SELECT 1 FROM audit_event e WHERE e.id=NEW.snapshot_evidence_id AND e.owner_user_id=NEW.snapshot_owner_user_id AND e.kind='MESSAGE_WORKSPACE_SNAPSHOT' AND e.legacy_source='agent_workspace_turn_snapshot' AND e.message_id=NEW.id AND BINARY NEW.role=BINARY 'assistant' AND BINARY e.session_id=BINARY NEW.session_id AND BINARY e.legacy_key=BINARY CAST(NEW.workspace_snapshot_legacy_id AS CHAR) AND e.occurred_at IS NULL AND e.legacy_clock_json IS NOT NULL AND BINARY JSON_UNQUOTE(JSON_EXTRACT(e.legacy_clock_json,'$.sourceTable'))=BINARY 'agent_workspace_turn_snapshot' AND CAST(JSON_UNQUOTE(JSON_EXTRACT(e.legacy_clock_json,'$.sourceKey.id')) AS DECIMAL(20,0))=NEW.workspace_snapshot_legacy_id AND BINARY e.content_sha256=BINARY NEW.workspace_snapshot_sha256 AND BINARY JSON_UNQUOTE(JSON_EXTRACT(e.payload_json,'$.snapshotJson'))=BINARY NEW.workspace_snapshot_json) THEN
            SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Unknown chat projection requires its exact original audit clock evidence';
        END IF;
    END IF;
END$$

CREATE TRIGGER compact_legacy_chat_projection_update
BEFORE UPDATE ON chat_message FOR EACH ROW
BEGIN
    IF NEW.execution_run_id IS NOT NULL AND (NEW.execution_created_at IS NULL OR EXISTS(SELECT 1 FROM audit_event e WHERE e.id=NEW.execution_evidence_id AND e.legacy_clock_json IS NOT NULL)) THEN
        IF NEW.execution_created_at IS NOT NULL OR NEW.execution_legacy_id IS NULL OR NOT EXISTS(SELECT 1 FROM audit_event e WHERE e.id=NEW.execution_evidence_id AND e.owner_user_id=NEW.execution_owner_user_id AND e.kind='MESSAGE_EXECUTION' AND e.legacy_source='agent_message_execution' AND e.message_id=NEW.id AND BINARY NEW.role=BINARY 'assistant' AND BINARY e.session_id=BINARY NEW.session_id AND BINARY e.legacy_key=BINARY CAST(NEW.execution_legacy_id AS CHAR) AND e.occurred_at IS NULL AND e.legacy_clock_json IS NOT NULL AND BINARY JSON_UNQUOTE(JSON_EXTRACT(e.legacy_clock_json,'$.sourceTable'))=BINARY 'agent_message_execution' AND CAST(JSON_UNQUOTE(JSON_EXTRACT(e.legacy_clock_json,'$.sourceKey.id')) AS DECIMAL(20,0))=NEW.execution_legacy_id AND BINARY e.run_id=BINARY NEW.execution_run_id) THEN
            SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Unknown chat projection requires its exact original audit clock evidence';
        END IF;
    END IF;
    IF NEW.snapshot_evidence_id IS NOT NULL AND (NEW.workspace_snapshot_created_at IS NULL OR EXISTS(SELECT 1 FROM audit_event e WHERE e.id=NEW.snapshot_evidence_id AND e.legacy_clock_json IS NOT NULL)) THEN
        IF NEW.workspace_snapshot_created_at IS NOT NULL OR NEW.workspace_snapshot_legacy_id IS NULL OR NOT EXISTS(SELECT 1 FROM audit_event e WHERE e.id=NEW.snapshot_evidence_id AND e.owner_user_id=NEW.snapshot_owner_user_id AND e.kind='MESSAGE_WORKSPACE_SNAPSHOT' AND e.legacy_source='agent_workspace_turn_snapshot' AND e.message_id=NEW.id AND BINARY NEW.role=BINARY 'assistant' AND BINARY e.session_id=BINARY NEW.session_id AND BINARY e.legacy_key=BINARY CAST(NEW.workspace_snapshot_legacy_id AS CHAR) AND e.occurred_at IS NULL AND e.legacy_clock_json IS NOT NULL AND BINARY JSON_UNQUOTE(JSON_EXTRACT(e.legacy_clock_json,'$.sourceTable'))=BINARY 'agent_workspace_turn_snapshot' AND CAST(JSON_UNQUOTE(JSON_EXTRACT(e.legacy_clock_json,'$.sourceKey.id')) AS DECIMAL(20,0))=NEW.workspace_snapshot_legacy_id AND BINARY e.content_sha256=BINARY NEW.workspace_snapshot_sha256 AND BINARY JSON_UNQUOTE(JSON_EXTRACT(e.payload_json,'$.snapshotJson'))=BINARY NEW.workspace_snapshot_json) THEN
            SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Unknown chat projection requires its exact original audit clock evidence';
        END IF;
    END IF;
END$$
