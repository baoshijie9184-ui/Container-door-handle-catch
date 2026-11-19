#!/usr/bin/env python3
"""Install the additive native-unit extension on a restored monolith MySQL schema."""
import argparse
from pathlib import Path
import re
import subprocess

parser = argparse.ArgumentParser()
parser.add_argument("--container", required=True)
parser.add_argument("--schema", required=True)
parser.add_argument("--check", action="store_true", help="Verify the installed extension without DDL")
args = parser.parse_args()
if not re.fullmatch(r"[A-Za-z0-9_]{1,64}", args.schema):
    parser.error("Invalid schema identifier")

def mysql(statement):
    command = ["docker", "exec", "-i", args.container, "sh", "-c",
               'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysql -uroot -NB --raw "$1"', "--", args.schema]
    return subprocess.check_output(command, input=statement, text=True).strip()

def columns(table):
    return set(mysql("SELECT column_name FROM information_schema.columns WHERE table_schema=DATABASE() "
                     f"AND table_name='{table}'").splitlines())

source = Path(__file__).resolve().parents[2] / "sql/mysql/compact/007-provider-budgets.sql"
text = source.read_text().split("ALTER TABLE ", 1)[1]
# The two ALTER statements each commit atomically. A retry verifies and skips a completed table.
parts = ["ALTER TABLE " + part for part in text.split("\nALTER TABLE ")]
operations = [
    ("llm_quota", {"native_unit","native_limit","native_opening_used","native_reserved","native_spent","native_rates"}),
    ("llm_usage", {"native_reserved_delta","native_spent_delta","native_detail","native_command"}),
]
if len(parts)!=len(operations):
    raise SystemExit("Unexpected migration layout")
for (table, keys), sql in zip(operations, parts):
    found = columns(table)
    if not found or not sql.startswith("ALTER TABLE "+table+"\n"):
        raise SystemExit("Missing target or mismatched migration: "+table)
    if keys <= found:
        continue
    if args.check or keys & found:
        raise SystemExit("Incomplete provider budget extension: "+table)
    mysql(sql)
    if not keys <= columns(table):
        raise SystemExit("Column readback failed: "+table)
checks = mysql("SELECT constraint_name FROM information_schema.table_constraints WHERE constraint_schema=DATABASE() "
               "AND constraint_name IN ('ck_native_budget','ck_native_budget_entry','uq_native_budget_command')").splitlines()
if len(checks)!=3:
    raise SystemExit("Budget constraints or command uniqueness missing")
print("Verified provider budget columns and constraints on " + args.schema)
