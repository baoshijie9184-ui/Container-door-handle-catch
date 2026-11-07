CREATE TRIGGER compact_legacy_clock_parent_chat_session_update
BEFORE UPDATE ON chat_session FOR EACH ROW
BEGIN
    IF (EXISTS(SELECT 1 FROM workflow_instance w WHERE w.chat_action_session_id=OLD.session_id AND w.legacy_clock_json IS NOT NULL)) AND (NOT(BINARY NEW.session_id<=>BINARY OLD.session_id)) THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='A cascade would remove or rekey original legacy clock evidence';
    END IF;
END$$

CREATE TRIGGER compact_legacy_clock_parent_chat_session_delete
BEFORE DELETE ON chat_session FOR EACH ROW
BEGIN
    IF (EXISTS(SELECT 1 FROM workflow_instance w WHERE w.chat_action_session_id=OLD.session_id AND w.legacy_clock_json IS NOT NULL)) THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='A cascade would remove or rekey original legacy clock evidence';
    END IF;
END$$
