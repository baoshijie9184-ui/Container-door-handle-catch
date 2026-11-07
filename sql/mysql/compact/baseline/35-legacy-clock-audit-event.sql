CREATE TRIGGER compact_legacy_clock_audit_event_update
BEFORE UPDATE ON audit_event FOR EACH ROW
BEGIN
    IF NOT(CAST(NEW.legacy_clock_json AS CHAR CHARACTER SET utf8mb4)<=>CAST(OLD.legacy_clock_json AS CHAR CHARACTER SET utf8mb4)) OR (OLD.legacy_clock_json IS NOT NULL AND OLD.kind IN ('MESSAGE_EXECUTION','MESSAGE_WORKSPACE_SNAPSHOT') AND (NOT(BINARY NEW.event_id<=>BINARY OLD.event_id) OR NOT(BINARY NEW.kind<=>BINARY OLD.kind) OR NOT(BINARY NEW.owner_user_id<=>BINARY OLD.owner_user_id) OR NOT(BINARY NEW.resource_type<=>BINARY OLD.resource_type) OR NOT(BINARY NEW.resource_id<=>BINARY OLD.resource_id) OR NOT(BINARY NEW.session_id<=>BINARY OLD.session_id) OR NOT(BINARY NEW.message_id<=>BINARY OLD.message_id) OR NOT(BINARY NEW.run_id<=>BINARY OLD.run_id) OR NOT(BINARY NEW.action<=>BINARY OLD.action) OR NOT(BINARY NEW.content_sha256<=>BINARY OLD.content_sha256) OR NOT(BINARY NEW.occurred_at<=>BINARY OLD.occurred_at) OR NOT(BINARY NEW.payload_version<=>BINARY OLD.payload_version) OR NOT(BINARY NEW.payload_json<=>BINARY OLD.payload_json) OR NOT(BINARY NEW.legacy_source<=>BINARY OLD.legacy_source) OR NOT(BINARY NEW.legacy_key<=>BINARY OLD.legacy_key))) THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Original legacy clock evidence must be retained unchanged';
    END IF;
END$$

CREATE TRIGGER compact_legacy_clock_audit_event_delete
BEFORE DELETE ON audit_event FOR EACH ROW
BEGIN
    IF OLD.legacy_clock_json IS NOT NULL THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Original legacy clock evidence must be retained unchanged';
    END IF;
END$$
