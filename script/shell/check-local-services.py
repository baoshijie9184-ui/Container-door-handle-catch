"""Read-only health checks for the configured development services; no model generation."""
from pathlib import Path
from urllib.parse import urlparse
import json
import sys

from dotenv import dotenv_values
import pymysql
import redis
import requests
from confluent_kafka.admin import AdminClient

root = Path(__file__).resolve().parents[2]
v = dotenv_values(root / ".env")
results = []


def check(name, operation):
    try:
        detail = operation()
        results.append({"service": name, "ready": True, "detail": detail})
    except Exception as error:
        results.append({"service": name, "ready": False, "errorType": type(error).__name__})


def mysql_health():
    url = urlparse(v["DB_URL"].removeprefix("jdbc:"))
    with pymysql.connect(host=url.hostname, port=url.port or 3306, user=v["DB_USERNAME"], password=v["DB_PASSWORD"],
                         database=url.path.lstrip("/"), charset="utf8mb4", connect_timeout=5, read_timeout=5) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.execute("SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME IN ('agent_run','agent_run_event')")
            tables = cursor.fetchone()[0]
            if v.get("AGENT_RUN_JOURNAL_ENABLED", "false").lower() == "true" and tables != 2:
                raise RuntimeError("Enabled run journal requires the V16 migration")
            detail = {"database": url.path.lstrip("/"), "journalTables": tables}
            cursor.execute("SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME IN ('agent_memory_preference','agent_memory_audit')")
            detail['memoryGovernanceTables']=cursor.fetchone()[0]
            if detail['memoryGovernanceTables']!=2:raise RuntimeError('Personal memory requires the explicit V26 migration')
            if v.get('AGENT_LOCAL_MCP_ENABLED','false').lower()=='true':
                cursor.execute("SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME IN ('agent_local_mcp','agent_local_mcp_audit')")
                detail['localMcpTables']=cursor.fetchone()[0]
                if detail['localMcpTables']!=2:raise RuntimeError('Local MCP requires the explicit V25 migration')
            cursor.execute("SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME IN ('organization_department','account_employee_binding','organization_binding_audit')")
            detail["organizationTables"] = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='employee' AND COLUMN_NAME='department_id'")
            if detail["organizationTables"] != 3 or cursor.fetchone()[0] != 1:
                raise RuntimeError("Account identity requires the explicit V20 migration")
            cursor.execute("SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME IN ('detection_quality_report','detection_report_audit','detection_report_command','detection_report_confirmation','detection_report_outbox')")
            detail["reportTables"] = cursor.fetchone()[0]
            if detail["reportTables"] != 5:
                raise RuntimeError("Report approval requires the explicit V21 migration")
            cursor.execute("SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='detection_report_agent_origin'")
            detail["reportOriginTables"] = cursor.fetchone()[0]
            if v.get("AGENT_SKILL_LINK_ENABLED", "false").lower() == "true":
                cursor.execute("SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='agent_skill_download'")
                detail['skillDownloadTables']=cursor.fetchone()[0]
                if detail['skillDownloadTables']!=1:raise RuntimeError('Linked Skills require V27')
                cursor.execute("SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='agent_skill_download' AND COLUMN_NAME IN ('target_skill_id','expected_skill_revision')")
                detail['skillUpgradeColumns']=cursor.fetchone()[0]
                if detail['skillUpgradeColumns']!=2:raise RuntimeError('Linked Skill upgrades require V28')
                cursor.execute("SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='agent_skill_storage_command'")
                detail['skillStorageCommandTables']=cursor.fetchone()[0]
                if detail['skillStorageCommandTables']!=1:raise RuntimeError('Skill cleanup requires V29')
            if v.get("AGENT_SKILL_EVOLUTION_ENABLED", "false").lower() == "true":
                cursor.execute("SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME IN ('agent_skill_source','agent_learned_skill','agent_skill_version','agent_skill_eval','agent_skill_audit')")
                detail["skillTables"] = cursor.fetchone()[0]
                if detail["skillTables"] != 5:
                    raise RuntimeError("Enabled skill evolution requires the explicit V23 migration")
                cursor.execute("SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='agent_skill_import'")
                detail['skillImportTables']=cursor.fetchone()[0]
                cursor.execute("SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='agent_skill_version' AND (COLUMN_NAME IN ('source_type','source_import_id') OR COLUMN_NAME='source_run_id' AND IS_NULLABLE='YES')")
                if cursor.fetchone()[0]!=3:
                    raise RuntimeError('Skill source metadata requires the explicit V24 migration')
            if detail["reportOriginTables"] != 1:
                raise RuntimeError("Agent report origin requires the explicit V22 migration")
            if v.get('APP_REPORT_EVENTS_ENABLED','false').lower()=='true':
                cursor.execute("SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='detection_report_outbox' AND COLUMN_NAME IN ('attempts','next_attempt_at','lease_token','lease_expires_at','delivered_at','last_error_code')")
                detail['reportEventColumns']=cursor.fetchone()[0]
                cursor.execute("SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME IN ('detection_report_event_receipt','detection_report_event_state')")
                detail['reportEventTables']=cursor.fetchone()[0]
                if detail['reportEventColumns']!=6 or detail['reportEventTables']!=2:raise RuntimeError('Report delivery requires V30')
            if v.get("AGENT_ACTION_CONFIRMATION_ENABLED", "false").lower() == "true":
                cursor.execute("SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME IN ('agent_pending_action','agent_action_audit')")
                detail["confirmationTables"] = cursor.fetchone()[0]
                if detail["confirmationTables"] != 2:
                    raise RuntimeError("Enabled action confirmation requires the V19 migration")
            return detail


def kafka_health():
    admin = AdminClient({"bootstrap.servers": v.get("APP_KAFKA_BOOTSTRAP_SERVERS", "127.0.0.1:9092"), "socket.timeout.ms": 4000})
    metadata = admin.list_topics(timeout=5)
    required = {v.get("APP_KAFKA_TOPIC_TASK_" + kind.upper()) or "detection.task." + kind
                for kind in ("created", "finished", "progress")}
    if v.get('APP_REPORT_EVENTS_ENABLED','false').lower()=='true':
        required.add(v.get('APP_REPORT_EVENTS_TOPIC') or 'detection.report.lifecycle.v1')
    if not required.issubset(metadata.topics):
        raise RuntimeError("Project topics not ready")
    return {"brokers": len(metadata.brokers), "projectTopics": sorted(required)}


http = requests.Session()
http.trust_env = False

def http_health(url):
    response = http.get(url, timeout=5)
    response.raise_for_status()
    data = response.json()
    if data.get("status") == "DOWN":
        raise RuntimeError("Health is DOWN")
    return {"httpStatus": response.status_code}


def memory_health():
    response=http.get(v.get("MEM0_SERVICE_URL","http://127.0.0.1:8081").rstrip("/")+"/health",timeout=5)
    response.raise_for_status();data=response.json()
    if not all(data.get(capability) for capability in ('governance','bridge_auth_configured','owned_edit','owned_pagination','write_receipts','lifecycle')):
        raise RuntimeError('Restart the authenticated memory bridge with owned edit/pagination and durable write receipts')
    return {'httpStatus':response.status_code,'governance':True,'bridgeAuthConfigured':True,'ownedEdit':True,'ownedPagination':True,'writeReceipts':True,'lifecycle':True}


check("MySQL", mysql_health)
check("Redis", lambda: {"ping": redis.Redis(host=v.get("REDIS_HOST", "localhost"), port=int(v.get("REDIS_PORT", 6379)),
    password=v.get("REDIS_PASSWORD") or None, db=int(v.get("REDIS_DATABASE", 0)), socket_connect_timeout=3).ping()})
check("Kafka", kafka_health)
check("Chroma", lambda: http_health(v.get("CHAT_ASSISTANT_CHROMA_BASE_URL", "http://127.0.0.1:8000").rstrip("/") + "/api/v2/heartbeat"))
check("Mem0", memory_health)
check("Backend", lambda: http_health("http://127.0.0.1:8080/actuator/health"))
print(json.dumps(results, ensure_ascii=False, indent=2))
output = root / "work/middlewares/services-health.json"
output.parent.mkdir(parents=True, exist_ok=True)
output.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
sys.exit(0 if all(item["ready"] for item in results) else 1)
