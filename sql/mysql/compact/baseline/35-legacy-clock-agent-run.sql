CREATE TRIGGER compact_legacy_clock_agent_run_update
BEFORE UPDATE ON agent_run FOR EACH ROW
BEGIN
    IF NOT(CAST(NEW.legacy_clock_json AS CHAR CHARACTER SET utf8mb4)<=>CAST(OLD.legacy_clock_json AS CHAR CHARACTER SET utf8mb4)) THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Original legacy clock evidence must be retained unchanged';
    END IF;
END$$

CREATE TRIGGER compact_legacy_clock_agent_run_delete
BEFORE DELETE ON agent_run FOR EACH ROW
BEGIN
    IF OLD.legacy_clock_json IS NOT NULL THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Original legacy clock evidence must be retained unchanged';
    END IF;
END$$
