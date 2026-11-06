#!/usr/bin/env python3
"""Restore an admitted private source/target backup into a new proof schema on ECS."""
import argparse
import json
from pathlib import Path
import sys

from compact_migration_runtime import Mysql, fresh_output, load_config, restore_backup


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True, type=Path)
    parser.add_argument('--backup-manifest', required=True, type=Path)
    parser.add_argument('--migration-evidence', required=True, type=Path)
    parser.add_argument('--restore-schema', required=True)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    try:
        config, _identity, _digest = load_config(args.config)
        output = fresh_output(args.output)
        mysql = Mysql(config, output); mysql.admitted_server()
        # Runtime restore creates its own technical receipt folder. The outer
        # private client files remain separate from the proof being delivered.
        result = restore_backup(mysql, args.backup_manifest, args.restore_schema, output / 'proof', args.migration_evidence)
        print(json.dumps({'kind': result['kind'], 'status': result['status'], 'output': str(output / 'proof/recovery-receipt.json')}))
        return 0
    except BaseException as error:
        print(json.dumps({'status': 'RESTORE_STOPPED_SOURCE_RETAINED', 'errorType': type(error).__name__}), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
