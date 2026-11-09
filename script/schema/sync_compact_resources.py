"""Build classpath SQL mirrors from the reviewed compact baseline; never execute SQL.

The full empty-schema artifact still comes from build_compact_schema.py. These
subsets serve component fixtures and carry the same columns and constraints.
"""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import re

from build_compact_schema import ROOT, split_top_level, without_comments

MIRRORS = {
    '001-coordination-state.sql': ('30-operations.sql', ('runtime_state',)),
    '005-workflow-runtime.sql': ('30-operations.sql', ('workflow_instance', 'scheduled_plan', 'audit_event')),
    '006-agent-run.sql': ('25-agent.sql', ('agent_run',)),
}


def expected():
    result = {}
    for output, (source, names) in MIRRORS.items():
        sql = (ROOT / 'sql/mysql/compact/baseline' / source).read_text(encoding='utf-8')
        definitions = {}
        for statement in split_top_level(without_comments(sql), ';'):
            match = re.match(r'CREATE TABLE (\w+)\s*\(', statement)
            if match:
                definitions[match.group(1)] = statement
        if set(names) - set(definitions):
            raise ValueError('A classpath source table is missing: ' + source)
        result[output] = ('-- Generated source mirror; execute only in an admitted ECS database.\n'
                          + '\n\n'.join(definitions[name].replace('CREATE TABLE ',
                                'CREATE TABLE IF NOT EXISTS ', 1) + ';' for name in names) + '\n')
    result['007-runtime-guards.sql'] = (ROOT / 'sql/mysql/compact/baseline/35-runtime-guards.sql').read_text(encoding='utf-8')
    for number, table in ((8, 'agent_run'), (9, 'agent_connector')):
        result[str(number).zfill(3) + '-' + table.replace('_', '-') + '-clock-guards.sql'] = (
            ROOT / 'sql/mysql/compact/baseline' / ('35-legacy-clock-' + table.replace('_', '-') + '.sql')
        ).read_text(encoding='utf-8')
    # Comment masking preserves offsets, but blank whitespace is not part of SQL.
    return {name: re.sub(r'(?m)^[ \t]+$', '', text) for name, text in result.items()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='Compare source mirrors without writing')
    args = parser.parse_args()
    directory = ROOT / 'doorhandle-framework/src/main/resources/db/compact'
    for name, text in expected().items():
        destination = directory / name
        if args.check:
            if not destination.is_file() or destination.read_text(encoding='utf-8-sig') != text:
                raise ValueError('Stale compact classpath mirror: ' + name)
        else:
            directory.mkdir(parents=True, exist_ok=True)
            destination.write_text(text, encoding='utf-8')
        print(name + ' ' + hashlib.sha256(text.encode('utf-8')).hexdigest())


if __name__ == '__main__':
    main()
