"""Verify collected original public receipts without tests, browser or network."""
import argparse
import importlib.util
import json
from pathlib import Path

spec = importlib.util.spec_from_file_location('collected_collaboration_bytes', Path(__file__).resolve().parents[1] / 'docker/collaboration-acceptance-evidence.py')
contract = importlib.util.module_from_spec(spec); spec.loader.exec_module(contract)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, required=True)
    parser.add_argument('--cleanup', type=Path, required=True)
    parser.add_argument('--proof', type=Path)
    parser.add_argument('--browser-report', type=Path)
    args = parser.parse_args()
    read = lambda path: contract.browser.decode(contract.browser.raw_file(path, 256 * 1024)[0])
    browser = contract.browser.decode(contract.browser.raw_file(args.browser_report, 32 * 1024 ** 2)[0]) if args.browser_report else None
    print(json.dumps(contract.validate_files(args.directory, read(args.cleanup), read(args.proof) if args.proof else None, browser), sort_keys=True))


if __name__ == '__main__': main()
