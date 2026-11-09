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

CREATE TRIGGER compact_legacy_clock_agent_run_binding_insert
AFTER INSERT ON agent_run FOR EACH ROW
BEGIN
    IF NOT(NEW.legacy_clock_json IS NULL OR COALESCE((((BINARY JSON_UNQUOTE(JSON_EXTRACT(NEW.legacy_clock_json,'$.sourceTable'))=BINARY 'agent_run') AND (BINARY NEW.id<=>BINARY CAST(JSON_UNQUOTE(JSON_EXTRACT(NEW.legacy_clock_json,'$.sourceKey.id')) AS DECIMAL(20,0))))),0)=1) THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Original legacy source key does not match target row';
    END IF;
END$$

CREATE TRIGGER compact_legacy_clock_agent_run_binding_update
AFTER UPDATE ON agent_run FOR EACH ROW
BEGIN
    IF NOT(NEW.legacy_clock_json IS NULL OR COALESCE((((BINARY JSON_UNQUOTE(JSON_EXTRACT(NEW.legacy_clock_json,'$.sourceTable'))=BINARY 'agent_run') AND (BINARY NEW.id<=>BINARY CAST(JSON_UNQUOTE(JSON_EXTRACT(NEW.legacy_clock_json,'$.sourceKey.id')) AS DECIMAL(20,0))))),0)=1) THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Original legacy source key does not match target row';
    END IF;
END$$
