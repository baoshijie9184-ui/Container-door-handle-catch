-- Preserve the old account_employee_binding -> users RESTRICT boundary after
-- embedding the association in users, including historical rows with no employee.
-- MySQL only, separator=$$. Application grants exclude DROP, ALTER and TRIGGER.
CREATE TRIGGER compact_identity_protect_delete
BEFORE DELETE ON users FOR EACH ROW
BEGIN
    IF OLD.binding_history_present=TRUE THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Account binding history prevents account deletion';
    END IF;
END$$

CREATE TRIGGER compact_identity_protect_update
BEFORE UPDATE ON users FOR EACH ROW
BEGIN
    IF OLD.binding_history_present=TRUE THEN
        IF NOT (NEW.id<=>OLD.id) OR NOT (NEW.binding_history_present<=>TRUE)
           OR NEW.binding_version<OLD.binding_version THEN
            SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Account binding identity and history cannot be reset';
        END IF;
    END IF;
END$$
