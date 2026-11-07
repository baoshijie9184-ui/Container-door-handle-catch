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
import importlib.util
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
import xml.etree.ElementTree as ET
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
VERIFY_TIMEOUT_SECONDS = 240 * 60
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
            # Tar iteration stops at its first zero header. Consume the stream's
            # read-ahead buffer as well as the gzip footer before accepting it.
            # This runs only after successful validation, preserving any caller
            # exception, and keeps padding under the same expansion bound.
            for block in iter(lambda: source.fileobj.read(1024 * 1024), b""):
                require(not block.strip(b"\0"), "Archive contains trailing non-padding bytes")


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
    if name in ("driver.log", "reports/receipt.json", "reports/python.xml", "reports/migration.json", "reports/tool-runtime.json"):
        return True
    if name.startswith("reports/") and name[len("reports/"):] in LOG_NAMES:
        return True
    if re.fullmatch(r"reports/java-(?:suite-[0-9]{3}|source-regression)\.log", name):
        return True
    return bool(re.fullmatch(r"reports/(?:source-regression/)?java/[A-Za-z0-9_.-]+/surefire-reports/TEST-[A-Za-z0-9_.$-]+\.xml", name))


def evidence_files(checkout, evidence, driver):
    candidates = [("driver.log", driver)]
    candidates += [("reports/" + name, evidence / name)
                   for name in ("receipt.json", "python.xml", "migration.json", "tool-runtime.json", *sorted(LOG_NAMES))]
    candidates += [("reports/" + path.name, path) for path in sorted(evidence.glob("java-*.log"))
                   if allowed_evidence("reports/" + path.name)]
    candidates += [("reports/java/" + path.relative_to(evidence / "java").as_posix(), path)
                   for path in sorted((evidence / "java").glob("*/surefire-reports/TEST-*.xml"))]
    candidates += [("reports/source-regression/java/" + path.relative_to(evidence / "source-regression/java").as_posix(), path)
                   for path in sorted((evidence / "source-regression/java").glob("*/surefire-reports/TEST-*.xml"))]
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
    # Older CI created this shared staging parent under the login umask (0775).
    # Restrict only this exact, owned directory before reading any child. Each
    # attempt and pre-staged fixture still passes the strict admission below.
    metadata = parent.lstat()
    require(stat.S_ISDIR(metadata.st_mode) and metadata.st_uid == os.getuid()
            and parent.resolve() == parent,
            "Verification root must belong to the current Unix user without links")
    os.chmod(parent, 0o700, follow_symlinks=False)
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
        # Create the shared per-attempt work parent before any tool can inherit
        # the login umask (0002). Custody requires this directory to be private.
        work = checkout / "work"
        work.mkdir(mode=0o700)
        owned_directory(work)
    return attempt_dir, checkout


def report_counts(evidence, references, selected, *, prefix):
    counts = dict(found=0, passed=0, failed=0, skipped=0)
    classes = {name: dict(counts) for name in selected}
    seen = set()
    require(isinstance(references, list) and references, 'The Java suite has no original XML reports')
    for item in references:
        require(isinstance(item, dict) and set(item) == {'path', 'bytes', 'sha256'}, 'Invalid Java report binding')
        name = item['path']
        require(isinstance(name, str) and name.startswith(prefix) and allowed_evidence('reports/' + name)
                and name not in seen, 'Java reports must use their independently owned suite archive')
        seen.add(name)
        path = evidence.joinpath(*member_path(name).parts)
        regular_file(path, MAX_FILE_BYTES)
        require(path.resolve() == path and path.is_relative_to(evidence)
                and path.stat().st_size == item['bytes'] and digest(path) == item['sha256'], 'Original Java XML bytes differ from their suite binding')
        root = ET.parse(path).getroot()
        for case in root.iter('testcase'):
            result = 'skipped' if case.find('skipped') is not None else 'failed' if (
                case.find('failure') is not None or case.find('error') is not None) else 'passed'
            counts['found'] += 1; counts[result] += 1
            actual = case.get('classname') or root.get('name', '')
            for requested, tally in classes.items():
                compared = actual if '.' in requested else actual.rsplit('.', 1)[-1]
                if compared == requested or compared.startswith(requested + '$'):
                    tally['found'] += 1; tally[result] += 1
    return counts, classes


def validate_java_suites(result, evidence, *, mysql):
    """Independently count the archived bytes; suite success is not a readiness flag."""
    suites = result.get('javaSuites')
    require(isinstance(suites, list) and 1 <= len(suites) <= 100, 'Verifier did not record its independent Java invocations')
    total = dict(found=0, passed=0, failed=0, skipped=0)
    selected, reports, seen_classes, seen_reports = {}, [], set(), set()
    for number, suite in enumerate(suites, 1):
        require(isinstance(suite, dict) and suite.get('id') == 'suite-' + str(number).zfill(3)
                and suite.get('status') == 'PASS', 'A Java invocation is missing or did not pass')
        names = suite.get('javaSelection')
        require(isinstance(names, list) and (names or not mysql)
                and all(isinstance(name, str) and re.fullmatch(r'[A-Za-z_$][A-Za-z0-9_$]*(?:\.[A-Za-z_$][A-Za-z0-9_$]*)*', name) for name in names),
                'A Java suite did not record its explicit selected classes')
        aliases = {name.rsplit('.', 1)[-1] for name in names}
        require(len(aliases) == len(names) and not aliases.intersection(seen_classes), 'Java class selections repeat between invocations')
        seen_classes.update(aliases)
        properties = suite.get('fixtureProperties')
        require(isinstance(properties, list) and (properties or not mysql), 'A MySQL suite did not record its fixture scope')
        actual, classes = report_counts(evidence, suite.get('reportFiles'), names, prefix='java/')
        require(actual == suite.get('javaTests') and classes == suite.get('selectedJavaClasses')
                and actual['passed'] > 0 and actual['failed'] == 0
                and (not mysql or actual['skipped'] == 0)
                and all(tally['passed'] > 0 and tally['failed'] == 0 and (not mysql or tally['skipped'] == 0) for tally in classes.values())
                and (not mysql or sum(tally['found'] for tally in classes.values()) == actual['found']),
                'A Java suite count differs from actual XML or a selected class failed, skipped or did not execute')
        for item in suite['reportFiles']:
            require(item['path'] not in seen_reports, 'Original Java XML is reused by multiple invocations')
            seen_reports.add(item['path']); reports.append(item)
        selected.update(classes)
        for key in total:
            total[key] += actual[key]
    require(total == result.get('javaTests') and selected == result.get('selectedJavaClasses')
            and reports == result.get('javaReportFiles'), 'The Java aggregate does not equal its independently archived invocations')
    regression = result.get('sourceRegression')
    if regression is not None:
        require(isinstance(regression, dict) and regression.get('status') == 'PASS'
                and regression.get('id') == 'source-regression' and regression.get('fixtureProperties') == [],
                'Ordinary Java regression inherited fixture flags or did not pass')
        names = regression.get('javaSelection')
        require(isinstance(names, list) and names and len(names) == len(set(names)), 'Ordinary Java regression did not record its audited pure-logic classes')
        actual, classes = report_counts(evidence, regression.get('reportFiles'), names, prefix='source-regression/java/')
        require(actual == regression.get('javaTests') and classes == regression.get('selectedJavaClasses')
                and actual['passed'] > 0 and actual['failed'] == 0
                and all(tally['passed'] > 0 and tally['failed'] == tally['skipped'] == 0 for tally in classes.values()),
                'Ordinary Java regression omitted or skipped an audited pure-logic class')


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
    tool_runtime, tool_value = None, None
    exit_code = 1
    try:
        unpack_source(archive, checkout, args.commit)
        script = checkout / "script" / "jenkins" / "verify-ecs.py"
        regular_file(script, MAX_FILE_BYTES)
        command = [sys.executable, "-B", str(script), "--output", str(evidence)]
        tool_manifest = inbox / 'tool-runtime/manifest.json'
        if tool_manifest.exists() or tool_manifest.is_symlink():
            module = checkout / 'script/jenkins/ecs-tool-runtime.py'
            regular_file(module, MAX_FILE_BYTES)
            spec = importlib.util.spec_from_file_location('admitted_ecs_tool_runtime', module)
            tool_runtime = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(tool_runtime)
            tool_value, tool_sha = tool_runtime.admit(tool_manifest, root=root, tag=args.tag,
                commit=args.commit, source_sha=args.source_sha256, identity=identity, source=checkout)
            record['toolRuntime'] = {'manifestSha256': tool_sha, 'images': tool_value['images']}
            command += ['--tool-manifest', str(tool_manifest), '--tool-manifest-sha256', tool_sha]
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
        if tool_value is not None:
            require(result.get('toolRuntime') == record['toolRuntime'],
                    'Verifier did not use this build immutable tool registration')
        require(process.returncode == 0 and result.get("status") == "PASS", "ECS verification did not pass")
        counts = result.get("javaTests", {})
        require(type(counts.get("passed")) is int and counts["passed"] > 0 and counts.get("failed") == 0,
                "Verifier did not record actual passing Java tests")
        validate_java_suites(result, evidence, mysql=args.scope == 'mysql')
        profile = checkout / 'script/jenkins/compact-acceptance.json'
        regular_file(profile, 1024 * 1024)
        require(result.get('acceptanceProfileSha256') == digest(profile), 'Verifier acceptance profile differs from the fixed source archive')
        record['javaSuiteCount'] = len(result['javaSuites'])
        record['acceptanceProfileSha256'] = result['acceptanceProfileSha256']
        record['sourceRegressionPassed'] = result.get('sourceRegression', {}).get('status') == 'PASS'
        if args.scope == "mysql":
            require(result.get("fixtureProperties") and result.get("javaSelection") and counts.get("skipped") == 0,
                    "MySQL verification did not record explicit fixture scope")
        if result.get("wholeMigrationRequested") is True:
            migration_counts = result.get("wholeMigrationTests", {})
            require(type(migration_counts.get("passed")) is int and migration_counts["passed"] > 0
                    and migration_counts.get("failed") == 0 and migration_counts.get("skipped") == 0,
                    "Whole migration acceptance did not actually pass")
            migration_file = evidence / "migration.json"
            regular_file(migration_file, 16384)
            require(hashlib.sha256(migration_file.read_bytes()).hexdigest() == result.get("wholeMigrationSummarySha256"),
                    "Whole migration public summary is missing or altered")
        record["status"] = "PASS"
        exit_code = 0
    except BaseException as error:
        record["errorType"] = type(error).__name__
        if isinstance(error, VerificationError):
            # All VerificationError messages above are fixed operator guidance, never private JSON.
            record["error"] = str(error)
    finally:
        stop_owned_process(process)
        if tool_value is not None:
            try:
                stopped = tool_runtime.cleanup(tool_value)
                tool_evidence = tool_runtime.evidence(tool_value, stopped)
                evidence.mkdir(mode=0o700, parents=True, exist_ok=True)
                file = evidence / 'tool-runtime.json'
                write_json(file, tool_evidence)
                record['toolRuntime'].update(cleanupStatus=stopped['status'], evidenceSha256=digest(file))
            except BaseException as error:
                record.update(status='FAILED', toolCleanupErrorType=type(error).__name__)
                exit_code = 1
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
    if record.get('toolRuntime') is not None:
        tools = record['toolRuntime']
        require(isinstance(tools, dict) and SHA.fullmatch(tools.get('manifestSha256', '')),
                'Tool admission evidence is incomplete')
        if record['status'] == 'PASS':
            require(tools.get('cleanupStatus') == 'STOPPED' and 'reports/tool-runtime.json' in catalog
                    and tools.get('evidenceSha256') == catalog['reports/tool-runtime.json']['sha256'],
                    'Passing tool evidence requires actual cleanup and its original report')
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
                    receipt_bytes = stream.read(MAX_RECEIPT_BYTES + 1)
                require(len(receipt_bytes) == entry.size, "Truncated verification receipt")
                record = json.loads(receipt_bytes.decode("utf8"))
                catalog = validate_envelope(record, args)
                output.mkdir(mode=0o700, parents=True)
                # Consumers bind this exact ECS file by SHA, including whitespace
                # and line endings. Parsing must not replace its original bytes.
                receipt_file = output / "verification-receipt.json"
                with receipt_file.open("xb") as destination:
                    os.chmod(receipt_file, 0o600)
                    destination.write(receipt_bytes)
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
