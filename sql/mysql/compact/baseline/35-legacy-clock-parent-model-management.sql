CREATE TRIGGER compact_legacy_clock_parent_model_management_update
BEFORE UPDATE ON model_management FOR EACH ROW
BEGIN
    IF (EXISTS(SELECT 1 FROM audit_event e WHERE e.detection_model_id=OLD.model_id AND e.legacy_clock_json IS NOT NULL)) AND (NOT(NEW.model_id<=>OLD.model_id)) THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='A cascade would remove or rekey original legacy clock evidence';
    END IF;
END$$

CREATE TRIGGER compact_legacy_clock_parent_model_management_delete
BEFORE DELETE ON model_management FOR EACH ROW
BEGIN
    IF (EXISTS(SELECT 1 FROM audit_event e WHERE e.detection_model_id=OLD.model_id AND e.legacy_clock_json IS NOT NULL)) THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='A cascade would remove or rekey original legacy clock evidence';
    END IF;
END$$
