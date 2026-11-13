"""Compile the closed SEMANTIC_INDEX derived-state namespace; never execute SQL.

Content chunks and immutable revisions retain their original meanings. This
projection contains model-space and current-source evidence, not another copy
of content, a credential, or a new business table.
"""
from pathlib import Path
import json
import re

ROOT = Path(__file__).resolve().parents[2]


def constraint():
    fields = {
        "protocolVersion": {"type": "integer", "enum": [1]},
        "kind": {"type": "string", "enum": ["KNOWLEDGE", "EXPERIENCE"]},
        "sourceId": {"type": "string", "pattern": "^[A-Za-z0-9_-]{1,128}$"},
        "sourceVersion": {"type": "integer", "minimum": 1, "maximum": 2147483647},
        "contentSha256": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
        "scope": {"type": "string", "maxLength": 100},
        "collection": {"type": "string", "pattern": "^[A-Za-z0-9_-]{1,128}$"},
        "profile": {"type": "string", "enum": ["siliconflow-bge-m3-v1", "explicit-openai-compatible"]},
        "model": {"type": "string", "pattern": "^[A-Za-z0-9_./:-]{1,256}$"},
        "dimensions": {"type": "integer", "minimum": 32, "maximum": 8192},
        "preprocessing": {"type": "string", "enum": ["utf8-newline-space-v1"]},
        "storageGeneration": {"type": "string", "enum": ["qdrant-bge-m3-v1", "qdrant-explicit-test-v1"]},
    }
    schema = json.dumps({"type": "object", "additionalProperties": False,
                         "required": list(fields), "properties": fields}, separators=(",", ":"))
    return ("CONSTRAINT ck_runtime_semantic_index CHECK (namespace<>'SEMANTIC_INDEX' OR COALESCE(("
            "owner_id>0 AND revision>=0 AND state_code IN ('PENDING','INDEXING','READY','FAILED') "
            "AND session_id IS NULL AND state_key IS NULL AND counter_value IS NULL "
            "AND provider IS NULL AND credential_sha256 IS NULL AND actor_user_id IS NULL AND request_id IS NULL "
            "AND window_started_at IS NULL AND window_ends_at IS NULL "
            "AND created_at IS NOT NULL AND updated_at IS NOT NULL AND payload_version=1 "
            "AND payload_json IS NOT NULL AND OCTET_LENGTH(payload_json)<=4096 "
            "AND JSON_SCHEMA_VALID('" + schema + "',payload_json) "
            "AND BINARY scope_key=BINARY CONCAT(JSON_UNQUOTE(JSON_EXTRACT(payload_json,'$.kind')),':',JSON_UNQUOTE(JSON_EXTRACT(payload_json,'$.sourceId'))) "
            "AND BINARY current_ref=BINARY CONCAT(JSON_UNQUOTE(JSON_EXTRACT(payload_json,'$.sourceId')),'@v',JSON_UNQUOTE(JSON_EXTRACT(payload_json,'$.sourceVersion')))),0)=1)")


def main():
    for relative in ("sql/mysql/compact/baseline/30-operations.sql", "sql/mysql/compact/001-coordination-state.sql"):
        path = ROOT / relative
        text = path.read_text(encoding="utf-8")
        text = re.sub(r"(?m)^\s*CONSTRAINT ck_runtime_semantic_index CHECK .*\n", "", text)
        anchor = re.search(r"(?m)^\s*CONSTRAINT ck_runtime_sdk CHECK", text)
        if not anchor:
            raise ValueError("Missing runtime semantic constraint anchor")
        path.write_text(text[:anchor.start()] + " " + constraint() + ",\n" + text[anchor.start():], encoding="utf-8")
    from sync_compact_resources import expected
    destination = ROOT / "doorhandle-framework/src/main/resources/db/compact/001-coordination-state.sql"
    destination.write_text(expected()["001-coordination-state.sql"], encoding="utf-8")
    print("SEMANTIC_INDEX_SQL_SOURCE_COMPILED_NOT_EXECUTED")


if __name__ == "__main__":
    main()
