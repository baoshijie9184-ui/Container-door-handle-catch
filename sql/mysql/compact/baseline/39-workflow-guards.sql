-- Legacy chat actions retain their original session ON DELETE/UPDATE CASCADE.
-- The ordinary FK column cannot also participate in a CHECK with these actions.
-- Cascades do not fire these triggers; they retain the existing action kind.
CREATE TRIGGER compact_workflow_chat_reference_insert
BEFORE INSERT ON workflow_instance FOR EACH ROW
BEGIN
    IF (NEW.kind='LEGACY_CHAT_ACTION' AND (BINARY NEW.kind<>BINARY 'LEGACY_CHAT_ACTION' OR NEW.chat_action_session_id IS NULL))
       OR (NEW.kind<>'LEGACY_CHAT_ACTION' AND NEW.chat_action_session_id IS NOT NULL) THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Legacy chat action session does not match its workflow kind';
    END IF;
END$$

CREATE TRIGGER compact_workflow_chat_reference_update
BEFORE UPDATE ON workflow_instance FOR EACH ROW
BEGIN
    IF OLD.kind='BUSINESS_COMMAND' AND (OLD.status='SUCCEEDED'
       OR NOT(BINARY NEW.kind<=>BINARY OLD.kind) OR NOT(BINARY NEW.workflow_id<=>BINARY OLD.workflow_id)
       OR NOT(NEW.owner_user_id<=>OLD.owner_user_id) OR NOT(NEW.actor_user_id<=>OLD.actor_user_id)
       OR NOT(BINARY NEW.idempotency_scope<=>BINARY OLD.idempotency_scope)
       OR NOT(BINARY NEW.request_id<=>BINARY OLD.request_id) OR NOT(BINARY NEW.request_sha256<=>BINARY OLD.request_sha256)
       OR NOT(BINARY NEW.payload_json<=>BINARY OLD.payload_json)) THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Business command identity and completed receipt are immutable';
    END IF;
    IF OLD.kind IN ('DETECTION_IDENTITY_COMMAND','DETECTION_IDENTITY_MAP_BATCH','DETECTION_IDENTITY_MAP_ITEM')
       OR (OLD.kind='DETECTION_IDENTITY_REPORT' AND OLD.status='COMPLETED') THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Completed detection identity receipts are immutable';
    END IF;
    IF OLD.digest_legacy_row_json IS NOT NULL AND
       (NOT(BINARY NEW.digest_legacy_row_json <=> BINARY OLD.digest_legacy_row_json)
        OR NOT(BINARY NEW.legacy_source <=> BINARY OLD.legacy_source)
        OR NOT(BINARY NEW.legacy_key <=> BINARY OLD.legacy_key)) THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Imported digest source evidence is immutable';
    END IF;
    IF (NEW.kind='LEGACY_CHAT_ACTION' AND (BINARY NEW.kind<>BINARY 'LEGACY_CHAT_ACTION' OR NEW.chat_action_session_id IS NULL))
       OR (NEW.kind<>'LEGACY_CHAT_ACTION' AND NEW.chat_action_session_id IS NOT NULL) THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Legacy chat action session does not match its workflow kind';
    END IF;
END$$

CREATE TRIGGER compact_workflow_identity_receipt_delete
BEFORE DELETE ON workflow_instance FOR EACH ROW
BEGIN
    IF OLD.kind IN ('BUSINESS_COMMAND','DETECTION_IDENTITY_COMMAND','DETECTION_IDENTITY_MAP_BATCH',
                    'DETECTION_IDENTITY_MAP_ITEM','DETECTION_IDENTITY_REPORT') THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Detection identity receipts must be retained';
    END IF;
END$$
