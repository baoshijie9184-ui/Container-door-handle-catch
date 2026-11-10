"""Validate collected original browser evidence bytes without executing browser/tests."""
import argparse
import importlib.util
import json
from pathlib import Path


spec = importlib.util.spec_from_file_location('collected_browser_bytes', Path(__file__).resolve().parents[1] / 'docker/collaboration-browser-evidence.py')
browser = importlib.util.module_from_spec(spec); spec.loader.exec_module(browser)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, required=True)
    parser.add_argument('--cleanup', type=Path, required=True)
    parser.add_argument('--proof', type=Path)
    args = parser.parse_args()
    cleanup = browser.decode(browser.raw_file(args.cleanup, 256 * 1024)[0])
    proof = browser.decode(browser.raw_file(args.proof, 256 * 1024)[0]) if args.proof else None
    print(json.dumps(browser.validate_files(args.directory, cleanup, proof), sort_keys=True))


if __name__ == '__main__': main()
