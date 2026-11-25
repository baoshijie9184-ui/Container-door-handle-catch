#!/usr/bin/env python3
"""Apifox-aligned QPS / TPS benchmark runner for DoorHandleCatch (java-cloud).

Runs read-only and safe write-path load tests against http://localhost:8080/
using real employee-number authentication (SUP-0001 / DET-0001), and emits
both an Apifox-importable collection JSON and a measured JSON/Markdown report.
"""
import argparse
import concurrent.futures
import http.cookiejar
import json
import math
import statistics
import time
import urllib.error
import urllib.request
from pathlib import Path


def make_opener():
    jar = http.cookiejar.CookieJar()
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar)), jar


def login(base_url: str, username: str, password: str):
    opener, jar = make_opener()
    body = json.dumps({"username": username, "password": password}).encode("utf-8")
    req = urllib.request.Request(
        f"{base_url}/api/auth/login",
        data=body,
        headers={"Content-Type": "application/json", "Origin": base_url},
        method="POST",
    )
    with opener.open(req, timeout=10) as resp:
        data = json.loads(resp.read().decode("utf-8"))
        if resp.status != 200 or data.get("code") != 200:
            raise RuntimeError(f"Login failed for {username}: {resp.status} {data}")
    return opener, jar


def run_stage(name: str, base_url: str, username: str, password: str,
              method: str, path: str, payload_fn, concurrency: int, duration_sec: float,
              extra_headers=None):
    # Pre-authenticate one opener per worker thread to simulate concurrent VUs
    openers = [login(base_url, username, password)[0] for _ in range(concurrency)]
    latencies_ms = []
    ok_count = 0
    err_count = 0
    status_counts = {}
    stop_at = time.perf_counter() + duration_sec

    def worker(idx: int):
        nonlocal ok_count, err_count
        opener = openers[idx]
        local_lat = []
        local_ok = 0
        local_err = 0
        local_statuses = {}
        seq = 0
        while time.perf_counter() < stop_at:
            seq += 1
            headers = {"Origin": base_url}
            if extra_headers:
                headers.update(extra_headers)
            data = None
            if payload_fn is not None:
                data = json.dumps(payload_fn(idx, seq)).encode("utf-8")
                headers["Content-Type"] = "application/json"
            req = urllib.request.Request(f"{base_url}{path}", data=data, headers=headers, method=method)
            t0 = time.perf_counter()
            try:
                with opener.open(req, timeout=15) as resp:
                    resp.read()
                    code = resp.status
                    dt = (time.perf_counter() - t0) * 1000.0
                    local_lat.append(dt)
                    local_statuses[code] = local_statuses.get(code, 0) + 1
                    if 200 <= code < 300:
                        local_ok += 1
                    else:
                        local_err += 1
            except urllib.error.HTTPError as e:
                dt = (time.perf_counter() - t0) * 1000.0
                local_lat.append(dt)
                local_statuses[e.code] = local_statuses.get(e.code, 0) + 1
                local_err += 1
            except Exception:
                dt = (time.perf_counter() - t0) * 1000.0
                local_lat.append(dt)
                local_statuses[0] = local_statuses.get(0, 0) + 1
                local_err += 1
        return local_lat, local_ok, local_err, local_statuses

    t_start = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as pool:
        futs = [pool.submit(worker, i) for i in range(concurrency)]
        for f in futs:
            lat, ok, err, st = f.result()
            latencies_ms.extend(lat)
            ok_count += ok
            err_count += err
            for k, v in st.items():
                status_counts[k] = status_counts.get(k, 0) + v
    elapsed = max(0.001, time.perf_counter() - t_start)
    total = ok_count + err_count
    latencies_ms.sort()

    def pct(p):
        if not latencies_ms:
            return 0.0
        k = min(len(latencies_ms) - 1, max(0, math.ceil(p / 100.0 * len(latencies_ms)) - 1))
        return round(latencies_ms[k], 2)

    return {
        "name": name,
        "method": method,
        "path": path,
        "concurrency": concurrency,
        "durationSec": round(elapsed, 2),
        "totalRequests": total,
        "okCount": ok_count,
        "errCount": err_count,
        "errorRatePct": round((err_count / total * 100.0) if total else 100.0, 3),
        "throughput": round(ok_count / elapsed, 2),
        "p50Ms": pct(50),
        "p95Ms": pct(95),
        "p99Ms": pct(99),
        "avgMs": round(statistics.mean(latencies_ms), 2) if latencies_ms else 0.0,
        "statusCounts": status_counts,
    }


def export_apifox_collection(base_url: str, out_path: Path):
    collection = {
        "apifoxProject": "1.0.0",
        "info": {
            "name": "DoorHandleCatch java-cloud 90+ QPS/TPS 压测套件",
            "description": "核心热点读(QPS)、业务分页读(QPS)、核心写(TPS)、AI/向量隔离压测集合",
        },
        "baseUrl": base_url,
        "scenarios": [
            {"id": "hot-read-auth", "name": "热点读-登录态校验", "method": "GET", "path": "/api/auth/check", "targetQps": 300, "targetP95Ms": 100},
            {"id": "hot-read-device-stats", "name": "热点读-设备统计概览", "method": "GET", "path": "/api/devices/stats", "targetQps": 300, "targetP95Ms": 100},
            {"id": "page-read-devices", "name": "分页读-设备列表", "method": "GET", "path": "/api/devices?page=1&size=10", "targetQps": 100, "targetP95Ms": 300},
            {"id": "page-read-reports", "name": "分页读-质检报告列表", "method": "GET", "path": "/api/detection/reports?page=1&size=20", "targetQps": 100, "targetP95Ms": 300},
            {"id": "page-read-models", "name": "分页读-检测模型列表", "method": "GET", "path": "/api/models?page=1&size=10", "targetQps": 100, "targetP95Ms": 300},
            {"id": "ai-catalog-read", "name": "AI隔离基线-模型目录", "method": "GET", "path": "/agui/models", "targetQps": 50, "targetP95Ms": 300},
        ],
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(collection, ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost:8080")
    parser.add_argument("--supervisor", default="SUP-0001")
    parser.add_argument("--employee", default="DET-0001")
    parser.add_argument("--password", default="123456")
    parser.add_argument("--duration", type=float, default=10.0)
    parser.add_argument("--out", default="work/reviews/apifox-benchmark-result.json")
    parser.add_argument("--collection", default="work/reviews/apifox-doorhandle-suite.json")
    args = parser.parse_args()

    export_apifox_collection(args.base_url, Path(args.collection))

    results = [
        run_stage("热点读-登录态校验 (QPS)", args.base_url, args.supervisor, args.password,
                  "GET", "/api/auth/check", None, concurrency=30, duration_sec=args.duration),
        run_stage("热点读-设备统计概览 (QPS)", args.base_url, args.supervisor, args.password,
                  "GET", "/api/devices/stats", None, concurrency=30, duration_sec=args.duration),
        run_stage("业务分页读-设备列表 (QPS)", args.base_url, args.supervisor, args.password,
                  "GET", "/api/devices?page=1&size=10", None, concurrency=20, duration_sec=args.duration),
        run_stage("业务分页读-报告列表 (QPS)", args.base_url, args.supervisor, args.password,
                  "GET", "/api/detection/reports?page=1&size=20", None, concurrency=20, duration_sec=args.duration),
        run_stage("业务分页读-模型列表 (QPS)", args.base_url, args.supervisor, args.password,
                  "GET", "/api/models?page=1&size=10", None, concurrency=20, duration_sec=args.duration),
        run_stage("AI/Agent基线-模型目录 (QPS)", args.base_url, args.employee, args.password,
                  "GET", "/agui/models", None, concurrency=10, duration_sec=args.duration),
    ]

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps({"baseUrl": args.base_url, "results": results}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
