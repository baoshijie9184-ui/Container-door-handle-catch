"""Verify one immutable source archive on an admitted ECS; collect only CI evidence.

ECS lifecycle is managed outside Jenkins.  The ``collect`` command only validates
and unpacks the bounded evidence archive on the local build node; it runs no tests.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import gzip
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import signal
import stat
import subprocess
import sys
import tarfile
import uuid
from urllib.request import ProxyHandler, Request, build_opener


MAX_SOURCE_ARCHIVE = 128 * 1024 * 1024
MAX_SOURCE_BYTES = 512 * 1024 * 1024
MAX_SOURCE_FILES = 50000
MAX_FILE_BYTES = 32 * 1024 * 1024
MAX_EVIDENCE_BYTES = 128 * 1024 * 1024
MAX_EVIDENCE_ARCHIVE = 64 * 1024 * 1024
MAX_EVIDENCE_FILES = 8192
MAX_RECEIPT_BYTES = 256 * 1024
MAX_FIXTURE_MARKER_BYTES = 16 * 1024
VERIFY_TIMEOUT_SECONDS = 90 * 60
TAG = re.compile(r"ci-[0-9]+-[a-f0-9]{12}")
SHA = re.compile(r"[a-f0-9]{64}")
COMMIT = re.compile(r"[a-f0-9]{40}")
ATTEMPT = re.compile(r"[a-f0-9]{32}")
LOG_NAMES = {
    "java.log", "python.log", "frontend-install.log", "frontend-test.log",
    "frontend-build.log", "frontend-agent-install.log", "frontend-agent-test.log",
    "frontend-agent-build.log",
}


class VerificationError(RuntimeError):
    pass


def require(value, message):
    if not value:
        raise VerificationError(message)


def now():
    return datetime.now(timezone.utc).isoformat()


def digest(path):
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def regular_file(path, maximum):
    require(path.is_file() and not path.is_symlink(), "Expected a regular file")
    require(path.stat().st_size <= maximum, "File exceeds the configured byte limit")


def write_json(path, value):
    with path.open("x", encoding="utf8") as stream:
        os.chmod(path, 0o600)
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def validate_request(args):
    require(COMMIT.fullmatch(args.commit or ""), "Expected the exact source commit")
    require(SHA.fullmatch(args.source_sha256 or ""), "Expected the source archive digest")
    require(TAG.fullmatch(args.tag or ""), "Invalid release tag")
    require(args.tag.endswith("-" + args.commit[:12]), "Release tag and commit differ")
    require(re.fullmatch(r"i-[a-z0-9]+", args.instance_id or ""), "Invalid admitted ECS instance")
    require(re.fullmatch(r"[a-f0-9]{32}", args.machine_id or ""), "Invalid admitted machine identity")
    require(ATTEMPT.fullmatch(args.attempt or ""), "Invalid verification attempt")


def ecs_identity(instance, machine):
    require(platform.system() == "Linux", "Verification must execute on Linux ECS")
    require(Path("/etc/machine-id").read_text().strip() == machine,
            "Machine identity differs from the admitted ECS")
    opener = build_opener(ProxyHandler({}))
    base = "http://100.100.100.200/latest/"
    request = Request(base + "api/token", data=b"", method="PUT", headers={
        "X-aliyun-ecs-metadata-token-ttl-seconds": "60"})
    with opener.open(request, timeout=3) as response:
        token = response.read(4096).decode()
    request = Request(base + "meta-data/instance-id", headers={
        "X-aliyun-ecs-metadata-token": token})
    with opener.open(request, timeout=3) as response:
        actual = response.read(256).decode().strip()
    require(actual == instance, "Instance identity differs from the admitted ECS")
    return {"instanceId": instance, "machineId": machine, "executionLocation": "ECS"}


def member_path(name):
    require(name and len(name) <= 2048 and "\\" not in name and ":" not in name and "\x00" not in name,
            "Unsafe archive entry name")
    value = PurePosixPath(name)
    require(not value.is_absolute() and all(part not in (".", "..") for part in name.split("/") if part),
            "Unsafe archive entry path")
    require(bool(value.parts), "Empty archive entry")
    return value


class BoundedReader:
    """Bound all expanded tar bytes, including hidden PAX/long-name metadata."""

    def __init__(self, original, limit):
        self.original, self.limit, self.read_bytes = original, limit, 0

    def read(self, size=-1):
        remaining = self.limit - self.read_bytes
        amount = remaining + 1 if size < 0 else min(size, remaining + 1)
        block = self.original.read(amount)
        self.read_bytes += len(block)
        require(self.read_bytes <= self.limit, "Archive expanded bytes exceed the configured limit")
        return block


@contextmanager
def bounded_tar(path, limit):
    with gzip.open(path, "rb") as expanded:
        with tarfile.open(fileobj=BoundedReader(expanded, limit), mode="r|") as source:
            yield source


def unpack_source(archive, destination, commit):
    files, total, seen = 0, 0, set()
    with bounded_tar(archive, MAX_SOURCE_BYTES) as source:
        for entry in source:
            files += 1
            require(files <= MAX_SOURCE_FILES, "Too many source archive entries")
            relative = member_path(entry.name)
            require(relative.parts[0] not in (".git", "work", "artifacts"),
                    "Source archive contains runtime or private storage")
            require(relative.as_posix() not in seen, "Duplicate source archive entry")
            seen.add(relative.as_posix())
            require(entry.isfile() or entry.isdir(), "Links and special archive entries are forbidden")
            require(0 <= entry.size <= MAX_FILE_BYTES, "Source archive entry is too large")
            total += entry.size
            require(total <= MAX_SOURCE_BYTES, "Source archive exceeds the expansion limit")
            target = destination.joinpath(*relative.parts)
            require(target.is_relative_to(destination), "Source archive escaped checkout")
            if entry.isdir():
                target.mkdir(mode=0o700, parents=True, exist_ok=True)
                continue
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            with source.extractfile(entry) as original, target.open("xb") as output:
                os.chmod(target, 0o700 if entry.mode & 0o100 else 0o600)
                remaining = entry.size
                while remaining:
                    block = original.read(min(1024 * 1024, remaining))
                    require(bool(block), "Truncated source archive entry")
                    output.write(block)
                    remaining -= len(block)
        require(source.pax_headers.get("comment") == commit,
                "Git archive commit metadata differs from the requested source")
    require(files > 0, "Empty source archive")


def allowed_evidence(name):
    if name in ("driver.log", "reports/receipt.json", "reports/python.xml"):
        return True
    if name.startswith("reports/") and name[len("reports/"):] in LOG_NAMES:
        return True
    return bool(re.fullmatch(r"reports/java/[A-Za-z0-9_.-]+/surefire-reports/TEST-[A-Za-z0-9_.$-]+\.xml", name))


def evidence_files(checkout, evidence, driver):
    candidates = [("driver.log", driver)]
    candidates += [("reports/" + name, evidence / name)
                   for name in ("receipt.json", "python.xml", *sorted(LOG_NAMES))]
    candidates += [("reports/java/" + path.relative_to(evidence / "java").as_posix(), path)
                   for path in sorted((evidence / "java").glob("*/surefire-reports/TEST-*.xml"))]
    result, omitted, total = [], [], 0
    for name, path in candidates:
        if not path.exists():
            continue
        if len(result) >= MAX_EVIDENCE_FILES - 1:
            omitted.append("file-count-limit")
            break
        if (not allowed_evidence(name) or not path.is_file() or path.is_symlink()
                or path.resolve() != path or not path.is_relative_to(checkout)):
            omitted.append("unsafe-evidence-entry")
            continue
        size = path.stat().st_size
        if size > MAX_FILE_BYTES or total + size > MAX_EVIDENCE_BYTES - MAX_RECEIPT_BYTES:
            omitted.append("evidence-byte-limit")
            continue
        total += size
        result.append((name, path, size, digest(path)))
    return result, sorted(set(omitted))


def make_evidence(inbox, checkout, evidence, driver, record):
    files, omitted = evidence_files(checkout, evidence, driver)
    if omitted:
        record.update(status="FAILED", evidenceOmissions=omitted)
    record["reportFiles"] = [{"path": name, "bytes": size, "sha256": sha}
                             for name, _path, size, sha in files]
    receipt = checkout.parent / "verification-receipt.json"
    write_json(receipt, record)
    regular_file(receipt, MAX_RECEIPT_BYTES)
    archive = inbox / "verification-evidence.tar.gz"
    require(not archive.exists(), "Verification evidence for this release already exists")
    temporary = inbox / ("verification-evidence-" + record["attempt"] + ".pending.tar.gz")
    with temporary.open("xb") as raw:
        os.chmod(temporary, 0o600)
        with tarfile.open(fileobj=raw, mode="w:gz") as target:
            target.add(receipt, arcname="verification-receipt.json", recursive=False)
            for name, path, size, sha in files:
                require(path.stat().st_size == size and digest(path) == sha,
                        "Evidence changed while collecting the completed attempt")
                target.add(path, arcname=name, recursive=False)
    require(temporary.stat().st_size <= MAX_EVIDENCE_ARCHIVE,
            "Evidence compressed archive exceeds the configured byte limit; original evidence retained")
    temporary.rename(archive)
    return archive


def stop_owned_process(process):
    if process is None or process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=25)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait(timeout=10)


def owned_directory(path):
    require(path.exists() and not path.is_symlink() and path.resolve() == path,
            "Verification staging directory must exist without links")
    metadata = path.lstat()
    require(stat.S_ISDIR(metadata.st_mode) and metadata.st_uid == os.getuid(),
            "Verification staging directories must belong to the current Unix user")
    require(metadata.st_mode & 0o022 == 0,
            "Verification staging directories cannot be group or others writable")


def fixture_readiness(attempt_dir, checkout, args):
    owned_directory(attempt_dir)
    for name in ("verification-receipt.json", "verification-receipt.failed.json", ".verification-claimed"):
        path = attempt_dir / name
        require(not path.exists() and not path.is_symlink(),
                "Fixture staging has already been claimed or has a previous result; use a new build")
    require({path.name for path in attempt_dir.iterdir()} == {".fixtures-ready.json", "checkout"},
            "Fixture staging may contain only its readiness marker and checkout directory")
    owned_directory(checkout)
    require({path.name for path in checkout.iterdir()} == {"work"},
            "Pre-staged checkout may contain only its private work directory, never source or evidence")
    work = checkout / "work"
    owned_directory(work)
    evidence = work / "ci-evidence"
    require(not evidence.exists() and not evidence.is_symlink(),
            "Fixture staging cannot contain previous verification evidence")
    marker = attempt_dir / ".fixtures-ready.json"
    require(marker.is_file() and not marker.is_symlink() and marker.resolve() == marker,
            "Fixture readiness marker must be a regular file without links")
    metadata = marker.lstat()
    require(stat.S_ISREG(metadata.st_mode) and metadata.st_uid == os.getuid(),
            "Fixture readiness marker must belong to the current Unix user")
    require(stat.S_IMODE(metadata.st_mode) in (0o400, 0o600),
            "Fixture readiness marker must have private 0400 or 0600 permissions")
    require(metadata.st_size <= MAX_FIXTURE_MARKER_BYTES,
            "Fixture readiness marker exceeds the 16 KiB limit")

    def unique_fields(pairs):
        value = {}
        for key, item in pairs:
            require(key not in value, "Fixture readiness marker contains duplicate fields")
            value[key] = item
        return value

    ready = json.loads(marker.read_text(encoding="utf-8-sig"), object_pairs_hook=unique_fields)
    expected = {"schema": 1, "kind": "doorhandle-ci-fixtures", "release": args.tag,
                "commit": args.commit, "instanceId": args.instance_id, "machineId": args.machine_id}
    require(isinstance(ready, dict) and set(ready) == set(expected)
            and type(ready.get("schema")) is int and ready == expected,
            "Fixture readiness marker differs from this release, commit or admitted ECS")


def prepare_checkout(root, args, identity):
    parent = root / "verification"
    require(not parent.is_symlink(), "Verification root cannot be a link")
    parent.mkdir(mode=0o700, exist_ok=True)
    owned_directory(parent)
    attempt_dir = parent / args.tag
    checkout = attempt_dir / "checkout"
    if args.scope == "mysql":
        require(attempt_dir.exists(),
                "MySQL verification requires an explicitly pre-staged readiness marker and private fixtures")
        fixture_readiness(attempt_dir, checkout, args)
    else:
        require(not attempt_dir.exists() and not attempt_dir.is_symlink(),
                "Release already has a verification directory; use a new build")
        attempt_dir.mkdir(mode=0o700)
        owned_directory(attempt_dir)
    # Atomic mkdir admits this request once. A crashed or interrupted attempt is
    # retained for inspection and cannot be silently reclaimed by another build.
    claim = attempt_dir / ".verification-claimed"
    claim.mkdir(mode=0o700)
    write_json(claim / "claim.json", {"schema": 1, "kind": "doorhandle-ci-claim",
        "release": args.tag, "attempt": args.attempt, "commit": args.commit,
        "sourceSha256": args.source_sha256, "identity": identity, "scope": args.scope})
    if args.scope == "source":
        checkout.mkdir(mode=0o700)
    return attempt_dir, checkout


def run_verification(args):
    validate_request(args)
    # No directory creation, archive extraction or test process precedes identity admission.
    identity = ecs_identity(args.instance_id, args.machine_id)
    root = Path(args.root)
    require(root.is_absolute() and len(root.parts) > 2 and root.parts[1] in ("home", "srv", "opt")
            and ".." not in root.parts and root.resolve(strict=True) == root and root.is_dir(),
            "Expected an existing admitted release root without links")
    inbox = root / "inbox" / args.tag
    require(inbox.is_dir() and inbox.resolve() == inbox, "Expected the existing attempt inbox")
    archive = inbox / "source.tar.gz"
    regular_file(archive, MAX_SOURCE_ARCHIVE)
    require(digest(archive) == args.source_sha256, "Source archive checksum differs")
    require(not (inbox / "verification-evidence.tar.gz").exists(), "Release already has verification evidence")
    attempt_dir, checkout = prepare_checkout(root, args, identity)
    evidence = checkout / "work" / "ci-evidence"
    driver = checkout / "driver.log"
    record = {"schema": 1, "kind": "doorhandle-ecs-ci", "release": args.tag,
              "attempt": args.attempt, "commit": args.commit, "sourceSha256": args.source_sha256,
              "identity": identity, "scope": args.scope, "startedAt": now(), "status": "FAILED",
              "verificationExitCode": None, "lifecycle": "managed-outside-jenkins",
              "fixtureManifestProvided": bool(args.fixture_manifest),
              "fixtureReadinessValidated": args.scope == "mysql"}
    process = None
    exit_code = 1
    try:
        unpack_source(archive, checkout, args.commit)
        script = checkout / "script" / "jenkins" / "verify-ecs.py"
        regular_file(script, MAX_FILE_BYTES)
        command = [sys.executable, "-B", str(script), "--output", str(evidence)]
        if args.scope == "mysql":
            require(bool(args.fixture_manifest), "MySQL verification requires an explicit private manifest")
            manifest = Path(args.fixture_manifest)
            require(manifest.is_absolute() and manifest.is_relative_to(checkout / "work"),
                    "MySQL manifest must be within this attempt checkout/work")
            require(manifest.is_file(),
                    "Provision the MySQL manifest privately within this attempt checkout/work first; no database was created")
            require(manifest.resolve(strict=True) == manifest, "MySQL manifest cannot use symlinks")
            command += ["--fixture-manifest", str(manifest)]
        else:
            require(not args.fixture_manifest, "Ordinary source verification does not accept a MySQL manifest")
        environment = dict(os.environ)
        # Do not forward credentials or implicit Java/Python injection settings from SSH profiles.
        environment = {key: value for key, value in environment.items()
                       if key in ("PATH", "JAVA_HOME", "LANG", "LC_ALL", "MAVEN_CMD", "NODE_EXE", "NPM_CMD")}
        environment.update(DOORHANDLE_ECS_INSTANCE_ID=args.instance_id,
                           DOORHANDLE_ECS_MACHINE_ID=args.machine_id,
                           PYTHON_EXE=sys.executable, PYTHONDONTWRITEBYTECODE="1")
        with driver.open("xb") as output:
            os.chmod(driver, 0o600)
            process = subprocess.Popen(command, cwd=checkout, env=environment,
                                       stdin=subprocess.DEVNULL, stdout=output,
                                       stderr=subprocess.STDOUT, start_new_session=True)
            process.wait(timeout=VERIFY_TIMEOUT_SECONDS)
        record["verificationExitCode"] = process.returncode
        result_file = evidence / "receipt.json"
        regular_file(result_file, MAX_RECEIPT_BYTES)
        result = json.loads(result_file.read_text(encoding="utf8"))
        require(result.get("identity") == identity, "Verifier receipt belongs to another execution host")
        require(process.returncode == 0 and result.get("status") == "PASS", "ECS verification did not pass")
        counts = result.get("javaTests", {})
        require(type(counts.get("passed")) is int and counts["passed"] > 0 and counts.get("failed") == 0,
                "Verifier did not record actual passing Java tests")
        if args.scope == "mysql":
            require(result.get("fixtureProperties") and result.get("javaSelection") and counts.get("skipped") == 0,
                    "MySQL verification did not record explicit fixture scope")
        record["status"] = "PASS"
        exit_code = 0
    except BaseException as error:
        record["errorType"] = type(error).__name__
        if isinstance(error, VerificationError):
            # All VerificationError messages above are fixed operator guidance, never private JSON.
            record["error"] = str(error)
    finally:
        stop_owned_process(process)
        if process is not None:
            record["verificationExitCode"] = process.returncode
        record["finishedAt"] = now()
        try:
            make_evidence(inbox, checkout, evidence, driver, record)
        except BaseException as error:
            record["status"] = "FAILED"
            record["evidenceErrorType"] = type(error).__name__
            exit_code = 1
            # Replace only this attempt's own receipt; never retain a misleading PASS
            # after report packaging failed. Original reports remain on the server.
            try:
                failed_receipt = attempt_dir / "verification-receipt.failed.json"
                write_json(failed_receipt, record)
                failed_receipt.replace(attempt_dir / "verification-receipt.json")
            except BaseException:
                pass
        if record["status"] != "PASS":
            exit_code = 1
        print(json.dumps({key: record[key] for key in ("release", "attempt", "status", "scope")}), flush=True)
    return exit_code


def validate_envelope(record, args):
    require(record.get("schema") == 1 and record.get("kind") == "doorhandle-ecs-ci", "Unexpected evidence schema")
    expected = {"release": args.tag, "attempt": args.attempt, "commit": args.commit,
                "sourceSha256": args.source_sha256, "scope": args.scope,
                "identity": {"instanceId": args.instance_id, "machineId": args.machine_id,
                             "executionLocation": "ECS"}}
    require(all(record.get(key) == value for key, value in expected.items()),
            "Evidence is not bound to this exact source, host and verification attempt")
    require(record.get("status") in ("PASS", "FAILED") and record.get("lifecycle") == "managed-outside-jenkins",
            "Invalid verification result")
    if args.scope == "mysql":
        require(record.get("fixtureReadinessValidated") is True,
                "MySQL evidence does not confirm its one-time fixture readiness admission")
    files = record.get("reportFiles")
    require(isinstance(files, list) and len(files) < MAX_EVIDENCE_FILES, "Invalid evidence file catalog")
    catalog = {}
    total = 0
    for file in files:
        require(isinstance(file, dict) and set(file) == {"path", "bytes", "sha256"}, "Invalid report file metadata")
        name, size, sha = file["path"], file["bytes"], file["sha256"]
        require(isinstance(name, str) and allowed_evidence(name) and name not in catalog,
                "Unexpected or duplicate report file")
        require(type(size) is int and 0 <= size <= MAX_FILE_BYTES and isinstance(sha, str) and SHA.fullmatch(sha),
                "Invalid report file size or digest")
        total += size
        require(total <= MAX_EVIDENCE_BYTES - MAX_RECEIPT_BYTES, "Evidence catalog exceeds the byte limit")
        catalog[name] = file
    return catalog


def collect(args):
    validate_request(args)
    archive = Path(args.archive).absolute()
    regular_file(archive, MAX_EVIDENCE_ARCHIVE)
    require(archive.resolve() == archive, "Evidence archive cannot be a link")
    output = Path(args.output).absolute()
    base = (Path.cwd() / "artifacts" / "ecs").resolve()
    require(output.resolve() == output and output.is_relative_to(base) and output != base,
            "Evidence extraction must stay inside this checkout artifacts/ecs")
    require(not output.exists(), "Evidence extraction requires a fresh attempt directory")
    record, catalog, seen = None, {}, set()
    with bounded_tar(archive, MAX_EVIDENCE_BYTES + 16 * 1024 * 1024) as source:
        for count, entry in enumerate(source, 1):
            require(count <= MAX_EVIDENCE_FILES, "Too many evidence archive entries")
            relative = member_path(entry.name)
            name = relative.as_posix()
            require(entry.isfile() and name not in seen, "Non-regular or duplicate evidence entry")
            seen.add(name)
            if count == 1:
                require(name == "verification-receipt.json" and 0 <= entry.size <= MAX_RECEIPT_BYTES,
                        "Evidence archive must begin with its bounded verification receipt")
                with source.extractfile(entry) as stream:
                    record = json.loads(stream.read(MAX_RECEIPT_BYTES + 1).decode("utf8"))
                catalog = validate_envelope(record, args)
                output.mkdir(mode=0o700, parents=True)
                write_json(output / "verification-receipt.json", record)
                continue
            require(name in catalog and entry.size == catalog[name]["bytes"], "Unlisted evidence archive entry")
            target = output.joinpath(*relative.parts)
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            check = hashlib.sha256()
            remaining = entry.size
            with source.extractfile(entry) as original, target.open("xb") as destination:
                os.chmod(target, 0o600)
                while remaining:
                    block = original.read(min(1024 * 1024, remaining))
                    require(bool(block), "Truncated evidence file")
                    check.update(block)
                    destination.write(block)
                    remaining -= len(block)
            require(check.hexdigest() == catalog[name]["sha256"], "Evidence file checksum differs")
    require(record is not None and seen == {"verification-receipt.json", *catalog}, "Missing expected evidence files")
    passed = record["status"] == "PASS" and record.get("verificationExitCode") == 0 and not record.get("evidenceOmissions")
    print(json.dumps({"release": args.tag, "attempt": args.attempt,
                      "evidenceValidated": True, "verificationPassed": passed}), flush=True)
    return 0 if passed else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", nargs="?", choices=("run", "collect"), default="run")
    parser.add_argument("--root")
    parser.add_argument("--tag", required=True)
    parser.add_argument("--source-sha256", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--instance-id", required=True)
    parser.add_argument("--machine-id", required=True)
    parser.add_argument("--scope", choices=("source", "mysql"), default="source")
    parser.add_argument("--fixture-manifest", default="")
    parser.add_argument("--attempt", default=uuid.uuid4().hex)
    parser.add_argument("--archive")
    parser.add_argument("--output")
    args = parser.parse_args()

    def interrupted(_number, _frame):
        raise KeyboardInterrupt("CI verification interrupted")

    if args.mode == "run":
        for number in (signal.SIGTERM, signal.SIGINT):
            signal.signal(number, interrupted)
        if hasattr(signal, "SIGHUP"):
            signal.signal(signal.SIGHUP, interrupted)
    try:
        if args.mode == "collect":
            require(args.archive and args.output, "Collect requires archive and output")
            return collect(args)
        require(args.root, "Run requires an existing release root")
        return run_verification(args)
    except BaseException as error:
        # Never print arbitrary exception content, subprocess output, secrets or private manifests.
        result = {"status": "FAILED", "errorType": type(error).__name__}
        if isinstance(error, VerificationError):
            result["error"] = str(error)  # Only fixed messages authored in this helper.
        print(json.dumps(result), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
