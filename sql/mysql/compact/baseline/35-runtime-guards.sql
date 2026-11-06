-- MySQL only. Statement separator is $$; the JDBC installer sets that separator.
-- The CLI schema assembler supplies DELIMITER directives around this resource.
-- Application accounts must not have DROP, ALTER or TRIGGER: TRUNCATE bypasses DELETE triggers.
CREATE TRIGGER compact_runtime_protect_delete
BEFORE DELETE ON runtime_state FOR EACH ROW
BEGIN
    IF OLD.namespace IN ('MODEL_CONFIG_CONTROL','MODEL_KEY_REVOCATION') THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Protected model runtime state cannot be deleted';
    END IF;
END$$

CREATE TRIGGER compact_runtime_protect_update
BEFORE UPDATE ON runtime_state FOR EACH ROW
BEGIN
    IF OLD.namespace IN ('MODEL_CONFIG_CONTROL','MODEL_KEY_REVOCATION') THEN
        IF NOT (NEW.namespace<=>OLD.namespace) OR NOT (NEW.owner_id<=>OLD.owner_id)
           OR NOT (NEW.scope_key<=>OLD.scope_key) OR NOT (NEW.created_at<=>OLD.created_at)
           OR NEW.revision<OLD.revision THEN
            SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Protected model runtime identity cannot be rewritten';
        END IF;
    ELSEIF NEW.namespace IN ('MODEL_CONFIG_CONTROL','MODEL_KEY_REVOCATION') THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Protected model runtime identity requires an insert';
    END IF;
    IF OLD.namespace='MODEL_CONFIG_CONTROL' THEN
        IF NEW.counter_value<OLD.counter_value OR (OLD.current_ref<>'0' AND NEW.current_ref='0') THEN
            SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Model configuration control cannot be reset';
        END IF;
    END IF;
    IF OLD.namespace='MODEL_KEY_REVOCATION' THEN
        IF NOT (NEW.provider<=>OLD.provider) OR NOT (NEW.credential_sha256<=>OLD.credential_sha256)
           OR NOT (NEW.actor_user_id<=>OLD.actor_user_id) OR NOT (NEW.request_id<=>OLD.request_id)
           OR NOT (NEW.state_code<=>OLD.state_code) OR NEW.counter_value<OLD.counter_value THEN
            SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Credential revocation is irreversible';
        END IF;
    END IF;
END$$
