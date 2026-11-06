"""Inventory literal Java/MyBatis legacy SQL references without executing any project code.

This is a source inventory, never a runtime-completeness or migration-acceptance gate.
Dynamic SQL, Python workers, initialization scripts and live database objects need
separate review. Include withdrawn intermediate table names, not only the 131
observed source tables: otherwise an invented compatibility table can be missed.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
WITHDRAWN = {"operation_job", "operation_item", "coordination_state"}
PATTERNS = (
    re.compile(r'\b(?:FROM|JOIN|INTO|UPDATE|DELETE\s+FROM)\s+[`"]?([a-z][a-z0-9_]*)', re.I),
    re.compile(r'@TableName\s*\(\s*"([a-z][a-z0-9_]*)"'),
)


def inventory():
    contract_path = ROOT / 'docs/database/compact-schema-contract.json'
    contract_bytes = contract_path.read_bytes()
    contract = json.loads(contract_bytes)
    legacy = set(contract['sourceTables']) - set(contract['expectedTargetTables'])
    names = legacy | WITHDRAWN
    references = {}
    inspected = 0
    for module in sorted(ROOT.glob('doorhandle-*')):
        main = module / 'src/main'
        if not main.is_dir():
            continue
        for path in sorted(main.rglob('*')):
            if not path.is_file() or path.suffix not in {'.java', '.xml'}:
                continue
            inspected += 1
            content = path.read_text(encoding='utf-8-sig')
            for pattern in PATTERNS:
                for match in pattern.finditer(content):
                    name = match.group(1).lower()
                    if name not in names:
                        continue
                    item = {'file': path.relative_to(ROOT).as_posix(),
                            'line': content.count('\n', 0, match.start()) + 1}
                    found = references.setdefault(name, [])
                    if item not in found:
                        found.append(item)
    return {
        'status': 'STATIC_ADOPTION_INVENTORY_NOT_RUNTIME_PROOF',
        'observedAtUtc': datetime.now(timezone.utc).isoformat(),
        'contractSha256': hashlib.sha256(contract_bytes).hexdigest(),
        'inspectedJavaAndMapperFiles': inspected,
        'legacyIdentifierCount': len(set(references) & legacy),
        'withdrawnIdentifierCount': len(set(references) & WITHDRAWN),
        'references': dict(sorted(references.items())),
        'limitations': ['Lexical references may occur in comments or documentation strings',
                        'Dynamic SQL, Python workers, initialization and migration scripts are not inspected',
                        'No live database, application, tests or ECS were accessed'],
    }


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    result = inventory()
    if args.output:
        output = args.output.resolve()
        if not output.is_relative_to(ROOT):
            parser.error('Inventory output must stay in this project workspace')
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print(json.dumps({key: result[key] for key in ('status', 'inspectedJavaAndMapperFiles', 'legacyIdentifierCount', 'withdrawnIdentifierCount')}))
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))
