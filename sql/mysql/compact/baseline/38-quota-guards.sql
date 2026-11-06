-- Imported incomplete usage is permanent unresolved accounting, not a resettable cache.
-- A future reconciliation protocol needs audited evidence; no session-variable bypass exists.
-- MySQL only, separator=$$. Application grants exclude DROP, ALTER and TRIGGER.
CREATE TRIGGER compact_quota_history_protect_delete
BEFORE DELETE ON llm_quota FOR EACH ROW
BEGIN
    IF OLD.unreconciled_legacy_attempts>0 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Unreconciled model usage prevents account deletion';
    END IF;
END$$

CREATE TRIGGER compact_quota_history_protect_update
BEFORE UPDATE ON llm_quota FOR EACH ROW
BEGIN
    IF OLD.unreconciled_legacy_attempts>0 THEN
        IF NEW.unreconciled_legacy_attempts<OLD.unreconciled_legacy_attempts
           OR NOT (NEW.id<=>OLD.id) OR NOT (NEW.scope_type<=>OLD.scope_type)
           OR NOT (NEW.owner_user_id<=>OLD.owner_user_id)
           OR NOT (BINARY NEW.model_id<=>BINARY OLD.model_id)
           OR NOT (BINARY NEW.period_key<=>BINARY OLD.period_key) THEN
            SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Unreconciled model usage identity and count cannot be reset';
        END IF;
    END IF;
END$$
