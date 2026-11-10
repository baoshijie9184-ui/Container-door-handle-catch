-- The concrete model reference retains V3 ON UPDATE/DELETE CASCADE.
-- MySQL disallows CHECK on a column with cascading referential actions.
-- These guards close the kind/reference shape for ordinary DML without duplicating
-- the current model identity in a generated column or a string resource identifier.
CREATE TRIGGER compact_audit_model_reference_insert
BEFORE INSERT ON audit_event FOR EACH ROW
BEGIN
    IF (NEW.kind='DETECTION_MODEL_OPERATION' AND (BINARY NEW.kind<>BINARY 'DETECTION_MODEL_OPERATION' OR NEW.detection_model_id IS NULL))
       OR (NEW.kind<>'DETECTION_MODEL_OPERATION' AND NEW.detection_model_id IS NOT NULL) THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Model audit reference does not match its event kind';
    END IF;
END$$

CREATE TRIGGER compact_audit_model_reference_update
BEFORE UPDATE ON audit_event FOR EACH ROW
BEGIN
    IF OLD.kind IN ('OPERATIONS','DETECTION_ASSIGNMENT_IDENTITY','DETECTION_IDENTITY_BINDING_EVENT',
                    'DETECTION_IDENTITY_RECON_ITEM','DETECTION_IDENTITY_MISSING_NAME','IDENTITY_MIGRATION_CLOCK')
       OR OLD.digest_legacy_detail_json IS NOT NULL THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Detection identity evidence is append-only';
    END IF;
    IF (NEW.kind='DETECTION_MODEL_OPERATION' AND (BINARY NEW.kind<>BINARY 'DETECTION_MODEL_OPERATION' OR NEW.detection_model_id IS NULL))
       OR (NEW.kind<>'DETECTION_MODEL_OPERATION' AND NEW.detection_model_id IS NOT NULL) THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Model audit reference does not match its event kind';
    END IF;
END$$

CREATE TRIGGER compact_audit_identity_evidence_delete
BEFORE DELETE ON audit_event FOR EACH ROW
BEGIN
    IF OLD.kind IN ('OPERATIONS','DETECTION_ASSIGNMENT_IDENTITY','DETECTION_IDENTITY_BINDING_EVENT',
                    'DETECTION_IDENTITY_RECON_ITEM','DETECTION_IDENTITY_MISSING_NAME','IDENTITY_MIGRATION_CLOCK')
       OR OLD.digest_legacy_detail_json IS NOT NULL THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Detection identity evidence is append-only';
    END IF;
END$$
