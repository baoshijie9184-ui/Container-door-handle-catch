"""Opaque custody of the closed 36-file local inventory; never executes its data.

pack is workstation byte copying only. All restore/reuse commands require the
fixed source and an actual passing verification on the original ECS. There is
deliberately no source deletion, model loading, database reader or runtime mount.
"""
from __future__ import annotations

import argparse
import ctypes
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import sys
import tarfile
from urllib.request import ProxyHandler, Request, build_opener


ROOT = Path(__file__).absolute().parents[2]
SOURCE_ROOT = "D:/AI/lunwen1/DoorHandleCatch"
PROFILE = "additional-local-artifacts-v1"
KIND = "doorhandle-additional-local-artifact-custody"
CATALOG_SHA256 = "e1258807aae1df63412e2190268351b1d63e770219ce9aba2d760f2f1bae1383"
FILE_COUNT = 36
ORIGINAL_BYTES = 465240718
MAX_BYTES = 512 * 1024 ** 2
MAX_MANIFEST = 2 * 1024 ** 2
DISK_FLOOR = (2 * 1024 + 256) * 1024 ** 2
MEMORY_FLOOR = 1024 ** 3
SNAPSHOT = "additional-local-artifacts-snapshot"
RESTORE = "additional-local-artifacts-restore"
OWNER = "additional-local-artifacts-owner.json"
PUBLIC = "additional-local-artifacts-public-receipt.json"
SHA = re.compile(r"[a-f0-9]{64}")
GROUPS = {"doorhandle-server/uploads", "uploads", "logs", "work/cloud/wacga-runtime-v2",
          "work/cloud/wacga-runtime-v3", "work/cloud/wacga-runtime-v4", "work/cloud/pth-model", "historical-archives"}


class CustodyError(Exception):
    """Authored failures contain no data, paths or credentials."""


def need(value, message):
    if not value:
        raise CustodyError(message)


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf8")


def digest(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def safe(path, *, exists=True):
    path = Path(path)
    need(path.is_absolute() and ".." not in path.parts, "An absolute unlinked custody path is required")
    need(not any(p.is_symlink() or getattr(p, "is_junction", lambda: False)() for p in (path, *path.parents)),
         "Linked custody paths are refused")
    if os.name == "nt":
        for parent in (path, *path.parents):
            if parent.exists():
                need(not getattr(parent.lstat(), "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT,
                     "Windows custody reparse points are refused")
    need(not exists or path.exists(), "A required custody input is missing")
    need(path.resolve(strict=exists) == path, "Custody paths must be canonical")
    return path


def member_name(value):
    need(isinstance(value, str) and 0 < len(value) <= 512 and "\\" not in value and ":" not in value
         and all(part not in ("", ".", "..") for part in value.split("/")), "Unsafe custody member")
    return value


def read_json(path, maximum=MAX_MANIFEST, *, private=False):
    path = safe(path); info = path.stat()
    need(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_size <= maximum,
         "Custody metadata must be a bounded unlinked regular file")
    if private:
        need(info.st_uid == os.getuid() and not info.st_mode & 0o077, "Custody metadata must remain owner-only")
    def unique(pairs):
        value = {}
        for key, entry in pairs:
            need(key not in value, "Repeated custody JSON key")
            value[key] = entry
        return value
    return json.loads(path.read_bytes(), object_pairs_hook=unique)


def write_json(path, value):
    path = safe(path, exists=False)
    with os.fdopen(os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), "wb") as stream:
        stream.write(encoded(value)); stream.flush(); os.fsync(stream.fileno())


def fingerprint(info):
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns, info.st_mode, info.st_nlink


def windows_security(path, *, protect=False):
    """Read original NTFS SDDL, or protect only a newly created output directory."""
    from ctypes import wintypes as w
    adv = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.LocalFree.argtypes = [w.LPVOID]; kernel.LocalFree.restype = w.LPVOID
    if protect:
        class TokenUser(ctypes.Structure):
            _fields_ = [("sid", w.LPVOID), ("attributes", w.DWORD)]
        token = w.HANDLE(); size = w.DWORD(); text = w.LPWSTR(); descriptor = w.LPVOID()
        kernel.GetCurrentProcess.restype = w.HANDLE
        adv.OpenProcessToken.argtypes = [w.HANDLE, w.DWORD, ctypes.POINTER(w.HANDLE)]
        adv.GetTokenInformation.argtypes = [w.HANDLE, ctypes.c_int, w.LPVOID, w.DWORD, ctypes.POINTER(w.DWORD)]
        adv.ConvertSidToStringSidW.argtypes = [w.LPVOID, ctypes.POINTER(w.LPWSTR)]
        adv.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [w.LPCWSTR, w.DWORD, ctypes.POINTER(w.LPVOID), ctypes.POINTER(w.DWORD)]
        adv.SetFileSecurityW.argtypes = [w.LPCWSTR, w.DWORD, w.LPVOID]
        kernel.CloseHandle.argtypes = [w.HANDLE]
        need(adv.OpenProcessToken(kernel.GetCurrentProcess(), 8, ctypes.byref(token)), "Cannot obtain output owner identity")
        try:
            adv.GetTokenInformation(token, 1, None, 0, ctypes.byref(size))
            need(0 < size.value <= 65536, "Cannot size output owner identity")
            buffer = ctypes.create_string_buffer(size.value)
            need(adv.GetTokenInformation(token, 1, buffer, size, ctypes.byref(size)), "Cannot read output owner identity")
            sid = ctypes.cast(buffer, ctypes.POINTER(TokenUser)).contents.sid
            need(adv.ConvertSidToStringSidW(sid, ctypes.byref(text)), "Cannot encode output owner identity")
            need(adv.ConvertStringSecurityDescriptorToSecurityDescriptorW("D:P(A;OICI;FA;;;" + text.value + ")", 1,
                 ctypes.byref(descriptor), None), "Cannot construct private output permissions")
            need(adv.SetFileSecurityW(str(path), 0x80000004, descriptor), "Cannot protect private output directory")
        finally:
            if descriptor: kernel.LocalFree(descriptor)
            if text: kernel.LocalFree(ctypes.cast(text, w.LPVOID))
            kernel.CloseHandle(token)
        return None
    size = w.DWORD(); text = w.LPWSTR()
    adv.GetFileSecurityW.argtypes = [w.LPCWSTR, w.DWORD, w.LPVOID, w.DWORD, ctypes.POINTER(w.DWORD)]
    adv.ConvertSecurityDescriptorToStringSecurityDescriptorW.argtypes = [w.LPVOID, w.DWORD, w.DWORD,
        ctypes.POINTER(w.LPWSTR), ctypes.POINTER(w.DWORD)]
    adv.GetFileSecurityW(str(path), 7, None, 0, ctypes.byref(size))
    need(0 < size.value <= 65536, "Cannot size original NTFS permissions")
    buffer = ctypes.create_string_buffer(size.value)
    need(adv.GetFileSecurityW(str(path), 7, buffer, size, ctypes.byref(size)), "Cannot read original NTFS permissions")
    need(adv.ConvertSecurityDescriptorToStringSecurityDescriptorW(buffer, 1, 7, ctypes.byref(text), None),
         "Cannot encode original NTFS permissions")
    try:
        need(bool(text.value) and len(text.value) <= 16384, "Original NTFS permissions exceed their bound")
        return text.value
    finally:
        kernel.LocalFree(ctypes.cast(text, w.LPVOID))


def private_directory(path):
    safe(path, exists=False).mkdir(mode=0o700)
    if os.name == "nt":
        windows_security(path, protect=True)


def permissions(path):
    info = path.stat()
    value = {"mode": stat.S_IMODE(info.st_mode), "uid": info.st_uid, "gid": info.st_gid,
             "atimeNs": info.st_atime_ns, "mtimeNs": info.st_mtime_ns}
    if os.name == "nt": value["windowsSddl"] = windows_security(path)
    return value


def catalogue(rows):
    return hashlib.sha256(encoded(sorted([[r["group"], r["member"], r["bytes"], r["sha256"]] for r in rows]))).hexdigest()


def validate_rows(rows):
    need(isinstance(rows, list) and len(rows) == FILE_COUNT, "The complete closed custody inventory is required")
    seen = set(); total = 0
    for row in rows:
        need(isinstance(row, dict) and set(row) == {"member", "sourcePath", "group", "bytes", "sha256", "permissions"},
             "Unexpected custody member metadata")
        name = member_name(row["member"])
        need(name not in seen and row["group"] in GROUPS and type(row["bytes"]) is int and 0 <= row["bytes"] <= MAX_BYTES
             and isinstance(row["sha256"], str) and SHA.fullmatch(row["sha256"]), "Custody member differs from its closed plan")
        seen.add(name); total += row["bytes"]
        need(isinstance(row["sourcePath"], str) and row["sourcePath"].replace("\\", "/").casefold()
             == (SOURCE_ROOT.rstrip("/") + "/" + name).casefold(), "Custody source escaped its reviewed root")
        metadata = row["permissions"]; fields = {"mode", "uid", "gid", "atimeNs", "mtimeNs"}
        need(isinstance(metadata, dict) and fields <= set(metadata) <= fields | {"windowsSddl"}
             and all(type(metadata[k]) is int and metadata[k] >= 0 for k in fields) and metadata["mode"] <= 0o7777
             and ("windowsSddl" not in metadata or isinstance(metadata["windowsSddl"], str)
                  and 0 < len(metadata["windowsSddl"]) <= 16384), "Invalid private original permissions")
    need(total == ORIGINAL_BYTES and total <= MAX_BYTES and catalogue(rows) == CATALOG_SHA256,
         "Original custody names, groups, sizes or raw hashes changed")
    return rows


def validate_manifest(value):
    need(isinstance(value, dict) and set(value) == {"version", "kind", "profile", "status", "catalogSha256",
         "catalogFileSha256", "packedAtUtc", "originalFiles", "originalBytes", "files", "archiveEncoding", "archiveBytes", "archiveSha256"}
         and value["version"] == 1 and type(value["version"]) is int and value["kind"] == KIND and value["profile"] == PROFILE
         and value["status"] == "COMPLETE" and value["catalogSha256"] == CATALOG_SHA256
         and value["originalFiles"] == FILE_COUNT and value["originalBytes"] == ORIGINAL_BYTES
         and value["archiveEncoding"] == "TAR" and type(value["archiveBytes"]) is int and 0 < value["archiveBytes"] <= MAX_BYTES
         and all(isinstance(value[k], str) and SHA.fullmatch(value[k]) for k in ("catalogFileSha256", "archiveSha256"))
         and isinstance(value["packedAtUtc"], str), "Incomplete or unreviewed opaque custody manifest")
    return validate_rows(value["files"])


def pack(catalog_file, output):
    root = safe(SOURCE_ROOT); output = safe(output, exists=False)
    need(not output.exists() and output.is_relative_to(root / "work") and len(output.relative_to(root / "work").parts) >= 2
         and re.fullmatch(r"data-migration-[A-Za-z0-9_.-]+", output.relative_to(root / "work").parts[0]),
         "New custody packages must stay under project work/data-migration")
    catalog_file = safe(catalog_file); catalog_before = fingerprint(catalog_file.stat())
    source = read_json(catalog_file); catalog_sha = digest(catalog_file)
    need(set(source) == {"kind", "observedAtUtc", "readOnlySources", "notUploaded", "files", "bytes", "members"}
         and source["kind"] == "doorhandle-additional-local-data-inventory" and source["readOnlySources"] is True
         and source["notUploaded"] is True and source["files"] == FILE_COUNT and source["bytes"] == ORIGINAL_BYTES,
         "Expected the reviewed local byte-only inventory")
    need(isinstance(source["members"], list) and len(source["members"]) == FILE_COUNT,
         "The catalog must contain exactly the reviewed members")
    rows, states = [], {}
    for item in source["members"]:
        need(set(item) == {"group", "path", "bytes", "sha256"}, "Unexpected source catalog entry")
        path = Path(item["path"])
        if not path.is_absolute(): path = root / path
        need(path.is_absolute() and path.is_relative_to(root), "Catalog source escaped the project")
        rows.append({"member": path.relative_to(root).as_posix(), "sourcePath": str(path), "group": item["group"],
            "bytes": item["bytes"], "sha256": item["sha256"],
            "permissions": {"mode": 0, "uid": 0, "gid": 0, "atimeNs": 0, "mtimeNs": 0}})
    # Reject any extra/secret source before opening even one original file.
    validate_rows(rows)
    for row in rows:
        path = safe(row["sourcePath"]); info = path.stat()
        need(stat.S_ISREG(info.st_mode), "A reviewed custody source is not a regular file")
        row["permissions"] = permissions(path)
        need(info.st_size == row["bytes"] and digest(path) == row["sha256"] and fingerprint(path.stat()) == fingerprint(info),
             "Original bytes changed since inventory")
        states[row["member"]] = fingerprint(info)
    validate_rows(rows)
    need(safe(output.parent).is_dir(), "The approved custody output parent must already exist")
    need(shutil.disk_usage(output.parent).free >= DISK_FLOOR + MAX_BYTES + MAX_MANIFEST,
         "Insufficient space for this private custody package")
    private_directory(output)
    archive = output / "originals.tar"
    with os.fdopen(os.open(archive, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), "wb") as target:
        with tarfile.open(fileobj=target, mode="w", format=tarfile.PAX_FORMAT, dereference=True) as tar:
            for row in rows:
                path = safe(row["sourcePath"])
                need(fingerprint(path.stat()) == states[row["member"]], "Original metadata changed before copying")
                info = tarfile.TarInfo(row["member"]); info.size = row["bytes"]; info.mode = 0o600
                info.mtime = row["permissions"]["mtimeNs"] // 1000000000
                with path.open("rb") as stream:
                    need(fingerprint(os.fstat(stream.fileno())) == states[row["member"]], "Original source identity changed")
                    class CopyHash:
                        def __init__(self): self.checksum = hashlib.sha256(); self.copied = 0
                        def read(self, size):
                            block = stream.read(size); self.checksum.update(block); self.copied += len(block)
                            return block
                    copied = CopyHash(); tar.addfile(info, copied)
                    need(copied.copied == row["bytes"] and copied.checksum.hexdigest() == row["sha256"],
                         "Source changed within the archived byte stream")
                    need(fingerprint(os.fstat(stream.fileno())) == states[row["member"]], "Original changed while copying")
                need(fingerprint(safe(path).stat()) == states[row["member"]] and digest(path) == row["sha256"],
                     "Original bytes changed during preservation")
        target.flush(); os.fsync(target.fileno())
    need(archive.stat().st_size <= MAX_BYTES, "Custody archive exceeds its transport budget")
    for row in rows:
        path = safe(row["sourcePath"])
        need(fingerprint(path.stat()) == states[row["member"]] and digest(path) == row["sha256"],
             "An original changed before package completion")
    need(fingerprint(catalog_file.stat()) == catalog_before and digest(catalog_file) == catalog_sha,
         "Original inventory changed while packaging")
    value = {"version": 1, "kind": KIND, "profile": PROFILE, "status": "COMPLETE", "catalogSha256": CATALOG_SHA256,
        "catalogFileSha256": catalog_sha, "packedAtUtc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "originalFiles": FILE_COUNT, "originalBytes": ORIGINAL_BYTES, "files": rows, "archiveEncoding": "TAR",
        "archiveBytes": archive.stat().st_size, "archiveSha256": digest(archive)}
    validate_manifest(value); write_json(output / "custody.json", value)
    return {"status": "PACKED", "profile": PROFILE, "files": FILE_COUNT, "bytes": ORIGINAL_BYTES,
            "catalogSha256": CATALOG_SHA256, "archiveBytes": value["archiveBytes"], "archiveSha256": value["archiveSha256"],
            "manifestBytes": (output / "custody.json").stat().st_size, "manifestSha256": digest(output / "custody.json")}


def owner_path(path, *, directory=False):
    path = safe(path); info = path.stat()
    need(info.st_uid == os.getuid() and not info.st_mode & 0o077
         and (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode) and info.st_nlink == 1),
         "An owner-only unlinked custody resource is required")
    return path


def owned_ancestor(path):
    path = safe(path); info = path.stat()
    need(stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid() and not info.st_mode & 0o022,
         "Existing CI custody ancestors must remain owned and not writable by others")
    return path


def resource_guard(path, additional=0):
    disk = os.statvfs(path)
    memory = next((int(line.split()[1]) * 1024 for line in Path("/proc/meminfo").read_text().splitlines()
                   if line.startswith("MemAvailable:")), None)
    need(disk.f_bavail * disk.f_frsize >= DISK_FLOOR + additional and memory is not None and memory >= MEMORY_FLOOR,
         "Opaque custody resource reserve reached")


def identity(expected_instance, expected_machine):
    need(sys.platform == "linux" and re.fullmatch(r"i-[a-z0-9]+", expected_instance)
         and re.fullmatch(r"[a-f0-9]{32}", expected_machine)
         and Path("/etc/machine-id").read_text().strip() == expected_machine, "Custody requires the admitted ECS identity")
    opener = build_opener(ProxyHandler({})); base = "http://100.100.100.200/latest/"
    with opener.open(Request(base + "api/token", data=b"", method="PUT",
             headers={"X-aliyun-ecs-metadata-token-ttl-seconds": "60"}), timeout=4) as response:
        token = response.read(4096).decode()
    with opener.open(Request(base + "meta-data/instance-id", headers={"X-aliyun-ecs-metadata-token": token}), timeout=4) as response:
        need(response.read(256).decode().strip() == expected_instance, "Custody ECS instance differs")
    return {"instanceId": expected_instance, "machineId": expected_machine, "executionLocation": "ECS"}


def admit(args):
    need(re.fullmatch(r"[a-f0-9]{40}", args.commit) and re.fullmatch(r"ci-[1-9][0-9]*-[a-f0-9]{12}", args.tag)
         and args.tag.endswith("-" + args.commit[:12]) and SHA.fullmatch(args.source_sha256), "Fixed custody source identity required")
    observed = identity(args.expected_instance_id, args.expected_machine_id)
    root = safe(args.root); checkout = safe(root / "verification" / args.tag / "checkout")
    for parent in (root, root / "verification", checkout.parent, checkout):
        owned_ancestor(parent)
    need(ROOT == checkout, "Custody must run from this build fixed checkout")
    archive = safe(root / "inbox" / args.tag / "source.tar.gz")
    need(archive.stat().st_size <= MAX_BYTES and digest(archive) == args.source_sha256, "Fixed source archive changed")
    with tarfile.open(archive, "r:gz") as tar:
        helper = tar.getmember("script/jenkins/preserve-local-artifacts.py")
        need(tar.pax_headers.get("comment") == args.commit and helper.isfile() and 0 < helper.size <= 1024 ** 2
             and hashlib.sha256(tar.extractfile(helper).read(1024 ** 2 + 1)).hexdigest() == digest(safe(Path(__file__).absolute())),
             "Custody helper differs from this committed source archive")
    receipt_file = safe(checkout.parent / "verification-receipt.json")
    accepted = read_json(receipt_file, private=True)
    need(all(accepted.get(key) == value for key, value in {"status": "PASS", "verificationExitCode": 0,
         "release": args.tag, "commit": args.commit, "sourceSha256": args.source_sha256, "identity": observed}.items()),
         "Opaque custody requires this build actual passing ECS verification")
    work = owned_ancestor(checkout / "work")
    return work, {"version": 1, "kind": KIND, "profile": PROFILE, "release": args.tag, "commit": args.commit,
        "sourceSha256": args.source_sha256, "identity": observed, "verificationReceiptSha256": digest(receipt_file),
        "catalogSha256": CATALOG_SHA256, "files": FILE_COUNT, "bytes": ORIGINAL_BYTES}


def expected_inputs(args):
    need(all(isinstance(getattr(args, field), str) and SHA.fullmatch(getattr(args, field))
             for field in ("manifest_sha256", "archive_sha256"))
         and type(args.manifest_bytes) is int and 0 < args.manifest_bytes <= MAX_MANIFEST
         and type(args.archive_bytes) is int and 0 < args.archive_bytes <= MAX_BYTES, "Invalid custody input byte binding")
    return {"custody.json": {"bytes": args.manifest_bytes, "sha256": args.manifest_sha256},
            "originals.tar": {"bytes": args.archive_bytes, "sha256": args.archive_sha256}}


def prepare(args):
    work, context = admit(args); inputs = expected_inputs(args)
    need(not any((work / name).exists() or (work / name).is_symlink() for name in (SNAPSHOT, RESTORE, OWNER, PUBLIC)),
         "Custody requires a fresh attempt; previous evidence is retained")
    resource_guard(work, ORIGINAL_BYTES + sum(row["bytes"] for row in inputs.values()) + MAX_MANIFEST)
    write_json(work / OWNER, {**context, "inputs": inputs, "sourceCustodyReceiptSha256": getattr(args, "source_receipt_sha256", None)})
    private_directory(work / SNAPSHOT)
    for name in inputs:
        os.close(os.open(work / SNAPSHOT / name, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600))
    return {**context, "status": "PREPARED"}


def original_snapshot(args):
    work, context = admit(args)
    old = safe(args.source_snapshot_directory)
    root = safe(args.root); relative = old.relative_to(root / "verification")
    need(len(relative.parts) == 4 and re.fullmatch(r"ci-[1-9][0-9]*-[a-f0-9]{12}", relative.parts[0])
         and relative.parts[1:] == ("checkout", "work", SNAPSHOT) and relative.parts[0] != args.tag,
         "Reusable custody must be an earlier same-root fixed snapshot")
    need(int(relative.parts[0].split("-")[1]) < int(args.tag.split("-")[1]),
         "Reusable custody must precede the current build")
    owner_path(old, directory=True)
    for path in (old.parent, old.parent.parent, old.parent.parent.parent):
        owned_ancestor(path)
    old_work = old.parent; public_file = owner_path(old_work / PUBLIC)
    public = read_json(public_file, private=True)
    need(public.get("status") == "RESTORED_VERIFIED" and public.get("kind") == KIND and public.get("profile") == PROFILE
         and public.get("catalogSha256") == CATALOG_SHA256 and public.get("files") == FILE_COUNT
         and public.get("bytes") == ORIGINAL_BYTES and public.get("identity") == context["identity"]
         and public.get("release") == relative.parts[0] and re.fullmatch(r"[a-f0-9]{40}", public.get("commit", ""))
         and public["release"].endswith("-" + public["commit"][:12]), "Old custody receipt does not prove same-ECS success")
    old_verification = read_json(owner_path(old_work.parent.parent / "verification-receipt.json"), private=True)
    need(all(old_verification.get(k) == public[k] for k in ("release", "commit", "sourceSha256", "identity"))
         and old_verification.get("status") == "PASS" and old_verification.get("verificationExitCode") == 0
         and digest(old_work.parent.parent / "verification-receipt.json") == public["verificationReceiptSha256"],
         "Old custody lost its actual verification binding")
    need({path.name for path in old.iterdir()} == {"custody.json", "originals.tar"}, "Old custody snapshot member set changed")
    manifest_file = owner_path(old / "custody.json"); archive = owner_path(old / "originals.tar")
    manifest = read_json(manifest_file, private=True); validate_manifest(manifest)
    need(archive.stat().st_size <= MAX_BYTES, "Old custody transport exceeds its bound")
    need(digest(manifest_file) == public["manifestSha256"] and digest(archive) == public["archiveSha256"]
         and archive.stat().st_size == public["archiveBytes"] == manifest["archiveBytes"]
         and manifest["archiveSha256"] == public["archiveSha256"], "Old custody archive or private manifest changed")
    owner_path(old_work / RESTORE, directory=True)
    restored_receipt = owner_path(old_work / RESTORE / "restore-receipt.json")
    restored = read_json(restored_receipt, private=True)
    need(digest(restored_receipt) == public["restoreReceiptSha256"] and all(restored.get(k) == public[k]
         for k in ("status", "release", "commit", "sourceSha256", "identity", "catalogSha256", "files", "bytes",
                   "manifestSha256", "archiveSha256", "archiveBytes")), "Old custody restore receipt changed")
    return work, context, old, public, digest(public_file)


def describe(args):
    _, context, old, public, receipt_sha = original_snapshot(args)
    return {**context, "status": "DESCRIBED", "manifestBytes": (old / "custody.json").stat().st_size,
        "manifestSha256": public["manifestSha256"], "archiveBytes": public["archiveBytes"],
        "archiveSha256": public["archiveSha256"], "sourceCustodyReceiptSha256": receipt_sha}


def verify_restore(args):
    work, context = admit(args); inputs = expected_inputs(args)
    owner = read_json(owner_path(work / OWNER), private=True)
    need(all(owner.get(k) == v for k, v in context.items()) and owner.get("inputs") == inputs,
         "Custody owner binding differs from this attempt")
    snapshot = owner_path(work / SNAPSHOT, directory=True)
    need({p.name for p in snapshot.iterdir()} == set(inputs), "Custody snapshot file set changed")
    for name, binding in inputs.items():
        file = owner_path(snapshot / name)
        need(file.stat().st_size == binding["bytes"] and digest(file) == binding["sha256"], "Uploaded custody bytes changed")
    manifest = read_json(snapshot / "custody.json", private=True); rows = validate_manifest(manifest)
    need(manifest["archiveBytes"] == args.archive_bytes and manifest["archiveSha256"] == args.archive_sha256,
         "Custody archive does not match its private manifest")
    restore = safe(work / RESTORE, exists=False)
    need(not restore.exists() and not (work / PUBLIC).exists(), "Custody recovery output must be new")
    resource_guard(work, ORIGINAL_BYTES + MAX_MANIFEST); private_directory(restore)
    expected = {row["member"]: row for row in rows}; seen = set(); total = 0
    class BoundedInfo(tarfile.TarInfo):
        @staticmethod
        def checked_header(value):
            need(value.type in (tarfile.REGTYPE, tarfile.AREGTYPE, tarfile.XHDTYPE, tarfile.XGLTYPE)
                 and 0 <= value.size <= (MAX_BYTES if value.isfile() else 65536), "Foreign custody archive metadata")
            return value
        @classmethod
        def frombuf(cls, buf, encoding, errors):
            return cls.checked_header(super().frombuf(buf, encoding, errors))
        def _proc_member(self, archive):
            # Guard the raw header even when tarfile bypasses public frombuf.
            self.checked_header(self)
            return super()._proc_member(archive)
        def _proc_gnusparse_00(self, *unused):
            raise CustodyError("Foreign custody sparse metadata")
        _proc_gnusparse_01 = _proc_gnusparse_00
        _proc_gnusparse_10 = _proc_gnusparse_00
    with tarfile.open(snapshot / "originals.tar", "r:", tarinfo=BoundedInfo) as tar:
        for entry in tar:
            name = member_name(entry.name)
            need(entry.isfile() and name in expected and name not in seen and entry.size == expected[name]["bytes"],
                 "Custody archive contains an extra, changed or linked member")
            target = restore / name; target.parent.mkdir(mode=0o700, parents=True, exist_ok=True); safe(target, exists=False)
            checksum = hashlib.sha256(); copied = 0
            with tar.extractfile(entry) as source, os.fdopen(os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), "wb") as output:
                for chunk in iter(lambda: source.read(1024 * 1024), b""):
                    copied += len(chunk); total += len(chunk)
                    need(copied <= entry.size and total <= ORIGINAL_BYTES, "Custody expanded beyond its closed byte plan")
                    checksum.update(chunk); output.write(chunk); resource_guard(work)
                output.flush(); os.fsync(output.fileno())
            need(copied == entry.size and checksum.hexdigest() == expected[name]["sha256"]
                 and digest(target) == expected[name]["sha256"], "Restored custody member digest differs")
            metadata = expected[name]["permissions"]; os.utime(target, ns=(metadata["atimeNs"], metadata["mtimeNs"]))
            seen.add(name)
    need(seen == set(expected) and total == ORIGINAL_BYTES, "Custody archive omitted reviewed originals")
    receipt = {**context, "status": "RESTORED_VERIFIED", "manifestSha256": args.manifest_sha256,
        "archiveSha256": args.archive_sha256, "archiveBytes": args.archive_bytes,
        "sourceCustodyReceiptSha256": owner.get("sourceCustodyReceiptSha256"), "originalFilesDeleted": 0,
        "modelsExecuted": 0, "databasesOpened": 0}
    write_json(restore / "restore-receipt.json", receipt)
    public = {**receipt, "restoreReceiptSha256": digest(restore / "restore-receipt.json")}
    write_json(work / PUBLIC, public)
    return {**public, "publicReceiptSha256": digest(work / PUBLIC)}


def reuse(args):
    work, _, old, _, receipt_sha = original_snapshot(args)
    need(SHA.fullmatch(args.source_receipt_sha256 or "") and args.source_receipt_sha256 == receipt_sha,
         "Reusable custody changed since description")
    inputs = expected_inputs(args)
    for name, row in inputs.items():
        need((old / name).stat().st_size == row["bytes"] and digest(old / name) == row["sha256"], "Reusable input bytes changed")
    prepare(args)
    for name, row in inputs.items():
        source = owner_path(old / name); before = fingerprint(source.stat()); checksum = hashlib.sha256(); copied = 0
        with source.open("rb") as original, (work / SNAPSHOT / name).open("wb") as target:
            for chunk in iter(lambda: original.read(1024 * 1024), b""):
                copied += len(chunk); need(copied <= row["bytes"], "Reusable custody grew while copying")
                checksum.update(chunk); target.write(chunk); resource_guard(work)
            target.flush(); os.fsync(target.fileno())
        need(copied == row["bytes"] and checksum.hexdigest() == row["sha256"] and fingerprint(source.stat()) == before,
             "Reusable custody changed during server-side copying")
    need(digest(old.parent / PUBLIC) == receipt_sha and all(digest(old / name) == binding["sha256"]
         for name, binding in inputs.items()), "Original server custody changed before independent recovery")
    return verify_restore(args)


def main():
    parser = argparse.ArgumentParser(description=__doc__); commands = parser.add_subparsers(dest="action", required=True)
    packaging = commands.add_parser("pack"); packaging.add_argument("--catalog", required=True); packaging.add_argument("--output", required=True)
    for action in ("prepare", "verify-restore", "describe", "reuse"):
        p = commands.add_parser(action)
        for flag in ("root", "tag", "commit", "source-sha256", "expected-instance-id", "expected-machine-id"):
            p.add_argument("--" + flag, required=True)
        if action != "describe":
            p.add_argument("--manifest-sha256", required=True); p.add_argument("--archive-sha256", required=True)
            p.add_argument("--manifest-bytes", type=int, required=True); p.add_argument("--archive-bytes", type=int, required=True)
        if action in ("describe", "reuse"): p.add_argument("--source-snapshot-directory", required=True)
        if action == "reuse": p.add_argument("--source-receipt-sha256", required=True)
    args = parser.parse_args()
    try:
        result = pack(args.catalog, args.output) if args.action == "pack" else {
            "prepare": prepare, "verify-restore": verify_restore, "describe": describe, "reuse": reuse}[args.action](args)
        print(json.dumps(result, sort_keys=True))
    except BaseException as error:
        print(json.dumps({"status": "FAILED", "kind": KIND, "errorType": type(error).__name__}), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
