"""Fixed-source ECS verification of the explicitly selected free embedding model.

This is an independent component verification, never a compact-schema release
gate. The existing production containers, databases and vector volumes stay intact.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import uuid
import xml.etree.ElementTree as ET


LABEL = "io.doorhandle.embedding-verification"
MODULES = ["tests_python/test_memory_embedding.py", "tests_python/test_memory_llm_parameters.py",
           "tests_python/test_mem0_runtime_collection.py", "tests_python/test_memory_service_tenancy.py",
           "tests_python/test_free_embedding_pipeline.py", "tests_python/test_legacy_bge_migration.py"]


class ComponentError(ValueError):
    """Only authored diagnostics, containing no provider or private file content."""


def need(value, message):
    if not value: raise ComponentError(message)


def digest(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""): value.update(chunk)
    return value.hexdigest()


def write(path, value):
    with Path(path).open("x", encoding="utf-8") as stream:
        os.chmod(path, 0o600)
        json.dump(value, stream, ensure_ascii=True, indent=2)
        stream.write("\n")


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def cosine(a, b):
    return sum(x*y for x, y in zip(a, b)) / math.sqrt(sum(x*x for x in a)*sum(y*y for y in b))


def prepare_next_release_environment(runtime, root, tag, key):
    """Prepare only the existing private file; never restart a production service."""
    import fcntl
    runtime = Path(runtime)
    need(root.is_absolute() and root.resolve(strict=True) == root and runtime.is_absolute()
         and runtime.resolve(strict=True) == runtime and ".." not in runtime.parts
         and runtime.parent == root.parent, "Canonical original sibling runtime required")
    environment = runtime / "deploy/cloud.env"
    need(environment.resolve(strict=True) == environment and environment.is_file()
         and environment.stat().st_uid == os.getuid() and not environment.stat().st_mode & 0o077
         and environment.stat().st_size <= 1024 * 1024, "Private original environment required")
    state = root / "state"
    need(state.is_dir() and state.resolve(strict=True) == state, "Original deployment lock directory required")
    lock_file = state / "deploy.lock"
    need(not lock_file.is_symlink(), "Deployment lock must not be redirected")
    with lock_file.open("a+b") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        original = environment.read_bytes()
        credential = key.read_text().strip()
        need(re.fullmatch(r"sk-[A-Za-z0-9_-]{20,}", credential), "Invalid private embedding credential")
        desired = {"EMBEDDING_API_KEY": credential, "EMBEDDING_PROFILE": "siliconflow-bge-m3-v1",
            "EMBEDDING_BASE_URL": "https://api.siliconflow.cn/v1", "EMBEDDING_MODEL": "BAAI/bge-m3",
            "EMBEDDING_REQUESTS_PER_MINUTE": "60", "EMBEDDING_MAX_INPUT_BYTES": "8000", "EMBEDDING_BATCH_SIZE": "8"}
        seen, result = set(), []
        for line in original.decode("utf-8-sig").splitlines():
            found = re.match(r"^\s*(?:export\s+)?([A-Z][A-Z0-9_]*)\s*=", line)
            name = found[1] if found else None
            if name in desired:
                need(name not in seen, "Duplicate embedding setting in private environment")
                seen.add(name); result.append(name + "=" + desired[name])
            else:
                result.append(line)
        result.extend(name + "=" + value for name, value in desired.items() if name not in seen)
        content = ("\n".join(result) + "\n").encode("utf-8")
        backup = runtime / "deploy/embedding-backups"
        if not backup.exists(): backup.mkdir(mode=0o700)
        need(backup.resolve(strict=True) == backup and backup.stat().st_uid == os.getuid()
             and not backup.stat().st_mode & 0o077, "Private original environment backup directory required")
        original_backup = backup / (tag + ".env")
        with original_backup.open("xb") as stream:
            os.chmod(original_backup, 0o600)
            stream.write(original); stream.flush(); os.fsync(stream.fileno())
        pending = environment.with_name("cloud.env.embedding-" + uuid.uuid4().hex + ".pending")
        try:
            with pending.open("xb") as stream:
                os.chmod(pending, 0o600)
                stream.write(content); stream.flush(); os.fsync(stream.fileno())
            need(environment.read_bytes() == original, "Private environment changed during preparation")
            os.replace(pending, environment)
            directory = os.open(environment.parent, os.O_RDONLY | os.O_DIRECTORY)
            try: os.fsync(directory)
            finally: os.close(directory)
        finally:
            if pending.exists(): pending.unlink()
        need(environment.read_bytes() == content, "Prepared private environment readback differs")
    return {"status": "PREPARED_FOR_NEXT_RELEASE", "model": "BAAI/bge-m3", "originalEnvironmentSha256": hashlib.sha256(original).hexdigest(),
        "preparedEnvironmentSha256": hashlib.sha256(content).hexdigest(), "originalBackupRetained": True,
        "containersRestarted": False, "liveActivationPerformed": False}


def live(source, output, key):
    sys.path.insert(0, str(source))
    from memory_service import embedding_config as embedding
    from mem0.utils.factory import EmbedderFactory
    settings = {"EMBEDDING_API_KEY_FILE": str(key)}
    native = EmbedderFactory.create("openai", embedding.embedder_config(settings), None)
    native.client = native.client.with_options(timeout=20, max_retries=0)
    adapter = embedding.FreeBgeEmbedder(native, settings=settings)
    documents = ["集装箱门把手盖涂层出现划痕，需要质检员复核。",
                 "周末天气晴朗，准备去公园散步。", "系统界面默认采用白色背景和蓝色操作按钮。"]
    queries = ["门把手表面有刮伤，应该进行质量复检", "请使用浅色页面和蓝色操作按钮"]
    try:
        vectors = adapter.embed_batch(documents)
        query_vectors = [adapter.embed(text, "search") for text in queries]
        matches = [max(range(len(vectors)), key=lambda i: cosine(query, vectors[i])) for query in query_vectors]
        need(matches == [0, 2], "The free model did not retrieve the corresponding synthetic semantic examples")
        import chromadb
        client = chromadb.PersistentClient(path=str(output / "synthetic-chroma"))
        collection = client.create_collection(embedding.COLLECTION, embedding_function=None)
        embedding.bind_collection(collection)
        collection.add(ids=["quality", "weather", "interface"], documents=documents, embeddings=vectors,
                       metadatas=[{"user_id": "fixture-owner", "agent_id": "doorhandlecatch"}] * 3)
        private = {"queries": query_vectors, "expectedIds": ["quality", "interface"], "collection": embedding.COLLECTION}
        write(output / "synthetic-queries.json", private)
        write(output / "live-result.json", {"status": "PASS", "provider": "siliconflow", "model": embedding.MODEL,
            "dimensions": 1024, "providerRequests": len(adapter._calls), "embeddedTexts": 5,
            "syntheticSemanticQueries": 2, "paidFallbacks": 0, "businessDataUsed": False})
    finally: native.client.close()


def recover(source, output):
    sys.path.insert(0, str(source))
    from memory_service import embedding_config as embedding
    import chromadb
    proof = json.loads((output / "synthetic-queries.json").read_text())
    client = chromadb.PersistentClient(path=str(output / "restored-chroma"))
    collection = client.get_collection(proof["collection"], embedding_function=None)
    embedding.bind_collection(collection)
    need(collection.count() == 3, "Recovered synthetic index lost a record")
    for vector, expected in zip(proof["queries"], proof["expectedIds"]):
        page = collection.query(query_embeddings=[vector], n_results=1,
                                where={"user_id": "fixture-owner"}, include=["metadatas"])
        need(page["ids"] == [[expected]], "Recovered synthetic semantic retrieval differs")
    need(collection.get(where={"user_id": "another-owner"})["ids"] == [], "Synthetic retrieval crossed owners")
    write(output / "recovery-result.json", {"status": "PASS", "independentProcess": True,
        "newDirectory": True, "records": 3, "semanticQueries": 2, "providerRequests": 0})


def worker(source, output, key):
    # Tests use only fixture credentials and in-process HTTP transports. The live
    # subprocess below is the only code that receives the real secret file path.
    environment = {**os.environ, "PYTHONPATH": str(source), "MEM0_DATA_DIR": str(output / "fixture-memory"),
                   "MEM0_TELEMETRY": "false", "ANONYMIZED_TELEMETRY": "false"}
    result = subprocess.run([sys.executable, "-B", "-m", "pytest", *MODULES, "-q", "-p", "no:cacheprovider",
        "--basetemp=" + str(output / "pytest"), "--junitxml=" + str(output / "python.xml")],
        cwd=source, env=environment, timeout=300)
    need(result.returncode == 0, "Embedding component regression failed")
    helper = source / "script/jenkins/verify-free-embedding.py"
    subprocess.run([sys.executable, "-B", str(helper), "live", "--source", str(source),
                    "--output", str(output), "--key", str(key)], env=environment, check=True, timeout=120)
    # The creating process has exited; copy the whole now-quiescent synthetic
    # Chroma directory and reopen it in a third process without another API call.
    shutil.copytree(output / "synthetic-chroma", output / "restored-chroma")
    subprocess.run([sys.executable, "-B", str(helper), "recover", "--source", str(source),
                    "--output", str(output)], env=environment, check=True, timeout=90)


def host(args):
    verifier = load_module("embedding_source_verifier", Path(__file__).with_name("verify-remote.py"))
    need(verifier.COMMIT.fullmatch(args.commit) and verifier.SHA.fullmatch(args.source_sha256)
         and verifier.TAG.fullmatch(args.tag) and args.tag.endswith("-" + args.commit[:12]), "Fixed source identity required")
    identity = verifier.ecs_identity(args.instance_id, args.machine_id)
    root = Path(args.root)
    need(root.is_absolute() and root.resolve(strict=True) == root and root.parts[1] in ("home", "srv", "opt"), "Admitted ECS root required")
    inbox = root / "inbox" / args.tag
    archive = inbox / "source.tar.gz"
    verifier.regular_file(archive, verifier.MAX_SOURCE_ARCHIVE)
    need(digest(archive) == args.source_sha256, "Fixed source archive changed")
    tool_manifest = inbox / "tool-runtime/manifest.json"
    need(digest(tool_manifest) == args.tool_manifest_sha256, "Tool registration changed")
    tools = json.loads(tool_manifest.read_text())
    need(tools["release"] == args.tag and tools["commit"] == args.commit
         and tools["sourceSha256"] == args.source_sha256 and tools["identity"]["instanceId"] == identity["instanceId"]
         and tools["identity"]["machineId"] == identity["machineId"], "Tools belong to another attempt")
    image = tools["images"]["python"]
    need(re.fullmatch(r"sha256:[a-f0-9]{64}", image), "Immutable dependency image required")
    key = Path(args.key)
    need(key == inbox / "embedding.key" and key.resolve(strict=True) == key
         and key.is_file() and not key.stat().st_mode & 0o077 and key.stat().st_uid == os.getuid()
         and 1 <= key.stat().st_size <= 4096, "Owned private credential required")
    work = inbox / "embedding-verification"
    need(not work.exists(), "Use a fresh build; original embedding evidence is immutable")
    work.mkdir(mode=0o700)
    source, output = work / "source", work / "reports"
    source.mkdir(mode=0o700); output.mkdir(mode=0o700)
    verifier.unpack_source(archive, source, args.commit)
    need(digest(source / "script/jenkins/verify-free-embedding.py") == digest(Path(__file__))
         and digest(source / "script/jenkins/verify-remote.py") == digest(Path(verifier.__file__)), "Helpers differ from fixed source")
    token = uuid.uuid4().hex
    name, cid = "doorhandle-embedding-" + token[:20], None
    receipt = {"schema": 1, "kind": "doorhandle-free-embedding-verification", "status": "FAILED",
        "release": args.tag, "commit": args.commit, "sourceSha256": args.source_sha256, "identity": identity,
        "imageId": image, "originalRuntimeChanged": False, "productionReleaseAllowed": False}
    def docker(*values, timeout=30):
        return subprocess.run(["docker", *values], capture_output=True, timeout=timeout, check=True).stdout
    def original_runtime():
        ids = docker("ps", "-aq", "--no-trunc", "--filter", "label=com.docker.compose.project=doorhandlecatch-monolith").decode().split()
        need(bool(ids) and all(re.fullmatch(r"[a-f0-9]{64}", entry) for entry in ids), "Original project container inventory required")
        rows = json.loads(docker("inspect", *ids))
        return {row["Id"]: {"image": row["Image"], "running": row["State"]["Running"],
            "pid": row["State"]["Pid"], "startedAt": row["State"]["StartedAt"],
            "service": row["Config"]["Labels"]["com.docker.compose.service"]} for row in rows}
    original = original_runtime()
    receipt["originalRuntimeContainers"] = len(original)
    receipt["originalRuntimeStateSha256"] = hashlib.sha256(json.dumps(original, sort_keys=True).encode()).hexdigest()
    try:
        cid = docker("create", "--name", name, "--pull", "never", "--restart", "no", "--read-only",
            "--label", LABEL + "=" + token, "--label", "io.doorhandle.release=" + args.tag,
            # The cached dependency image was committed from the old Mem0
            # image and retains its Compose labels. Override both identities;
            # no test container may be discoverable as an original service.
            "--label", "com.docker.compose.project=doorhandle-embedding-" + token[:12],
            "--label", "com.docker.compose.service=embedding-test",
            "--user", str(os.getuid()) + ":" + str(os.getgid()), "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges", "--memory", "2g", "--memory-swap", "2g",
            "--cpus", "1", "--pids-limit", "256", "--tmpfs", "/tmp:rw,nosuid,nodev,size=256m",
            "--env", "MEM0_TELEMETRY=false", "--env", "ANONYMIZED_TELEMETRY=false", "--env", "PYTHONDONTWRITEBYTECODE=1",
            "--env", "HOME=/tmp", "--env", "XDG_CACHE_HOME=/tmp/cache", "--workdir", "/source", "--entrypoint", "/usr/local/bin/python",
            "--mount", "type=bind,src=" + str(source) + ",dst=/source,readonly",
            "--mount", "type=bind,src=" + str(output) + ",dst=/output",
            "--mount", "type=bind,src=" + str(key) + ",dst=/run/secrets/embedding,readonly",
            image, "-B", "/source/script/jenkins/verify-free-embedding.py", "worker",
            "--source", "/source", "--output", "/output", "--key", "/run/secrets/embedding").decode().strip()
        need(re.fullmatch(r"[a-f0-9]{64}", cid), "Owned container identity unavailable")
        created = json.loads(docker("inspect", cid))[0]
        need(created["Config"]["Labels"].get("com.docker.compose.project") == "doorhandle-embedding-" + token[:12]
             and created["Config"]["Labels"].get("com.docker.compose.service") == "embedding-test",
             "Dependency image inherited original service identity")
        with (output / "verification.log").open("xb") as log:
            os.chmod(log.name, 0o600)
            started = subprocess.run(["docker", "start", "-a", cid], stdout=log, stderr=subprocess.STDOUT, timeout=600)
        row = json.loads(docker("inspect", cid))[0]
        need(started.returncode == 0 and row["State"]["ExitCode"] == 0 and not row["State"].get("OOMKilled"), "Embedding verification failed; original evidence retained")
        cases = list(ET.parse(output / "python.xml").getroot().iter("testcase"))
        required = {"test_memory_embedding": 28, "test_memory_llm_parameters": 14, "test_mem0_runtime_collection": 24,
                    "test_memory_service_tenancy": 5, "test_free_embedding_pipeline": 8, "test_legacy_bge_migration": 7}
        counts = {name: 0 for name in required}
        for case in cases:
            name = case.get("classname", "").rsplit(".", 1)[-1]
            need(name in counts, "An embedding testcase has no registered source module")
            counts[name] += 1
        need(all(counts[name] >= minimum for name, minimum in required.items())
             and all(not any(case.find(tag) is not None for tag in ("failure", "error", "skipped")) for case in cases), "Component test evidence is incomplete")
        live_result, recovered = [json.loads((output / file).read_text()) for file in ("live-result.json", "recovery-result.json")]
        need(live_result["status"] == recovered["status"] == "PASS" and live_result["providerRequests"] == 3
             and live_result["model"] == "BAAI/bge-m3" and live_result["dimensions"] == 1024
             and recovered["providerRequests"] == 0, "Embedding/recovery evidence differs from its fixed budget")
        receipt.update(componentTests=len(cases), componentModules=counts, live=live_result, recovery=recovered)
        need(original_runtime() == original, "Original application containers changed during embedding verification")
        prepared_environment = prepare_next_release_environment(args.runtime, root, args.tag, key)
        receipt.update(status="PASS", componentTests=len(cases), componentModules=counts, live=live_result, recovery=recovered,
                       nextReleaseEnvironment=prepared_environment)
    except Exception as error:
        receipt["errorType"] = type(error).__name__
        if isinstance(error, ComponentError): receipt["diagnostic"] = str(error)
        raise
    finally:
        stopped = False
        if cid:
            row = json.loads(docker("inspect", cid))[0]
            need(row["Id"] == cid and row["Image"] == image and row["Config"]["Labels"].get(LABEL) == token,
                 "Container ownership changed; no cleanup performed")
            if row["State"]["Running"]: docker("stop", "--time", "10", cid)
            final = json.loads(docker("inspect", cid))[0]
            need(not final["State"]["Running"] and final["State"]["Pid"] == 0, "Embedding container did not stop")
            docker("rm", cid)
            stopped = not docker("ps", "-aq", "--no-trunc", "--filter", "label=" + LABEL + "=" + token).strip()
        receipt["ownedCleanup"] = "STOPPED" if stopped else "NO_CONTAINER"
        receipt["originalRuntimeChanged"] = original_runtime() != original
        if receipt["originalRuntimeChanged"]: receipt["status"] = "FAILED"
        # Revoke the temporary file's access even on failed tests. The durable
        # source of the key remains Jenkins Credentials, never a CI artifact.
        key.unlink()
        names = ("python.xml", "verification.log", "live-result.json", "recovery-result.json")
        receipt["reportFiles"] = [{"path": name, "bytes": (output / name).stat().st_size,
            "sha256": digest(output / name)} for name in names if (output / name).is_file()]
        write(output / "receipt.json", receipt)
    print(json.dumps({"status": receipt["status"], "release": args.tag, "receiptSha256": digest(output / "receipt.json")}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("verify", "worker", "live", "recover"))
    for name in ("source", "output", "key", "root", "runtime", "tag", "commit", "source-sha256", "instance-id", "machine-id", "tool-manifest-sha256"):
        parser.add_argument("--" + name)
    args = parser.parse_args()
    if args.action == "verify": host(args)
    elif args.action == "worker": worker(Path(args.source), Path(args.output), Path(args.key))
    elif args.action == "live": live(Path(args.source), Path(args.output), Path(args.key))
    else: recover(Path(args.source), Path(args.output))


if __name__ == "__main__":
    try: main()
    except Exception as error:
        result = {"status": "FAILED", "errorType": type(error).__name__}
        if isinstance(error, ComponentError): result["diagnostic"] = str(error)
        print(json.dumps(result), file=sys.stderr)
        raise SystemExit(2)
