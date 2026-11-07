CREATE TRIGGER compact_legacy_clock_parent_users_update
BEFORE UPDATE ON users FOR EACH ROW
BEGIN
    IF (EXISTS(SELECT 1 FROM chat_session s JOIN workflow_instance w ON w.chat_action_session_id=s.session_id WHERE (s.user_id=OLD.id OR s.username=OLD.username) AND w.legacy_clock_json IS NOT NULL)) AND (NOT(NEW.id<=>OLD.id) OR NOT(BINARY NEW.username<=>BINARY OLD.username)) THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='A cascade would remove or rekey original legacy clock evidence';
    END IF;
END$$

CREATE TRIGGER compact_legacy_clock_parent_users_delete
BEFORE DELETE ON users FOR EACH ROW
BEGIN
    IF (EXISTS(SELECT 1 FROM chat_session s JOIN workflow_instance w ON w.chat_action_session_id=s.session_id WHERE (s.user_id=OLD.id OR s.username=OLD.username) AND w.legacy_clock_json IS NOT NULL)) THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='A cascade would remove or rekey original legacy clock evidence';
    END IF;
END$$
