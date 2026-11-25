#!/usr/bin/env python3
"""Write-path TPS, AI bulkhead isolation, and two-role (SUP-0001 x DET-0001) E2E verifier."""
import concurrent.futures
import http.cookiejar
import json
import math
import statistics
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

BASE = "http://localhost:8080"


def login(username: str, password: str = "123456"):
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    body = json.dumps({"username": username, "password": password}).encode("utf-8")
    req = urllib.request.Request(
        f"{BASE}/api/auth/login",
        data=body,
        headers={"Content-Type": "application/json", "Origin": BASE},
        method="POST",
    )
    with opener.open(req, timeout=10) as resp:
        data = json.loads(resp.read().decode("utf-8"))
        assert resp.status == 200 and data.get("code") == 200, f"login failed: {data}"
    return opener


def call_json(opener, method: str, path: str, payload=None, extra_headers=None):
    headers = {"Origin": BASE}
    if extra_headers:
        headers.update(extra_headers)
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(f"{BASE}{path}", data=data, headers=headers, method=method)
    try:
        with opener.open(req, timeout=15) as resp:
            raw = resp.read().decode("utf-8")
            return resp.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="ignore")
        try:
            body = json.loads(raw) if raw else {}
        except Exception:
            body = {"raw": raw[:200]}
        return e.code, body


def pct(arr, p):
    if not arr:
        return 0.0
    s = sorted(arr)
    k = min(len(s) - 1, max(0, math.ceil(p / 100.0 * len(s)) - 1))
    return round(s[k], 2)


def benchmark_write_tps(duration_sec: float = 8.0, concurrency: int = 16):
    # Create one temp session per worker for DET-0001 so writes hit MySQL cleanly without row-lock contention on a single row
    openers = [login("DET-0001") for _ in range(concurrency)]
    temp_sessions = []
    for idx, op in enumerate(openers):
        st, body = call_json(op, "POST", "/api/chat-assistant/sessions", {"title": f"tps-bench-{idx}"})
        assert st == 200 and body.get("code") == 200, f"create temp session failed: {st} {body}"
        temp_sessions.append(body["data"]["sessionId"])

    latencies = []
    ok = 0
    err = 0
    stop_at = time.perf_counter() + duration_sec

    def worker(i: int):
        op = openers[i]
        sid = temp_sessions[i]
        l_lat, l_ok, l_err = [], 0, 0
        seq = 0
        while time.perf_counter() < stop_at:
            seq += 1
            t0 = time.perf_counter()
            st, body = call_json(op, "PUT", f"/api/chat-assistant/sessions/{sid}/title", {"title": f"tps-{i}-{seq}"})
            dt = (time.perf_counter() - t0) * 1000.0
            l_lat.append(dt)
            if st == 200 and body.get("code") == 200:
                l_ok += 1
            else:
                l_err += 1
        return l_lat, l_ok, l_err

    t_start = time.perf_counter()
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as pool:
            for l_lat, l_ok, l_err in [f.result() for f in [pool.submit(worker, i) for i in range(concurrency)]]:
                latencies.extend(l_lat)
                ok += l_ok
                err += l_err
    finally:
        for i, sid in enumerate(temp_sessions):
            call_json(openers[i], "DELETE", f"/api/chat-assistant/sessions/{sid}")

    elapsed = max(0.001, time.perf_counter() - t_start)
    total = ok + err
    return {
        "name": "核心写事务-会话标题持久化 (TPS)",
        "concurrency": concurrency,
        "durationSec": round(elapsed, 2),
        "totalRequests": total,
        "okCount": ok,
        "errCount": err,
        "errorRatePct": round((err / total * 100.0) if total else 100.0, 3),
        "tps": round(ok / elapsed, 2),
        "p50Ms": pct(latencies, 50),
        "p95Ms": pct(latencies, 95),
        "p99Ms": pct(latencies, 99),
    }


def benchmark_bulkhead_isolation(duration_sec: float = 8.0):
    core_openers = [login("SUP-0001") for _ in range(20)]
    ai_openers = [login("DET-0001") for _ in range(10)]
    stop_at = time.perf_counter() + duration_sec

    def core_worker(i):
        op = core_openers[i]
        l_lat, l_ok, l_err = [], 0, 0
        while time.perf_counter() < stop_at:
            t0 = time.perf_counter()
            st, _ = call_json(op, "GET", "/api/devices/stats")
            l_lat.append((time.perf_counter() - t0) * 1000.0)
            if st == 200:
                l_ok += 1
            else:
                l_err += 1
        return l_lat, l_ok, l_err

    def ai_worker(i):
        op = ai_openers[i]
        l_lat, l_ok, l_err = [], 0, 0
        while time.perf_counter() < stop_at:
            t0 = time.perf_counter()
            st, _ = call_json(op, "GET", "/agui/models")
            l_lat.append((time.perf_counter() - t0) * 1000.0)
            if st == 200:
                l_ok += 1
            else:
                l_err += 1
        return l_lat, l_ok, l_err

    t_start = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=30) as pool:
        c_futs = [pool.submit(core_worker, i) for i in range(20)]
        a_futs = [pool.submit(ai_worker, i) for i in range(10)]
        c_lat, c_ok, c_err = [], 0, 0
        for f in c_futs:
            l, o, e = f.result()
            c_lat.extend(l); c_ok += o; c_err += e
        a_lat, a_ok, a_err = [], 0, 0
        for f in a_futs:
            l, o, e = f.result()
            a_lat.extend(l); a_ok += o; a_err += e
    elapsed = max(0.001, time.perf_counter() - t_start)
    return {
        "name": "AI并发下核心读舱壁隔离验证",
        "durationSec": round(elapsed, 2),
        "coreReadQps": round(c_ok / elapsed, 2),
        "coreReadP95Ms": pct(c_lat, 95),
        "coreReadErrors": c_err,
        "aiReadQps": round(a_ok / elapsed, 2),
        "aiReadP95Ms": pct(a_lat, 95),
        "aiReadErrors": a_err,
    }


def verify_two_role_e2e():
    sup = login("SUP-0001")
    det = login("DET-0001")
    checks = {}

    # 1. Board completed tasks visible to DET-0001 (matches new report dropdown)
    st, board = call_json(det, "GET", "/api/detection/board?page=1&size=20")
    rows = board.get("data", {}).get("records") or board.get("data", {}).get("items") or []
    completed = [r for r in rows if str(r.get("modelStatus") or r.get("status") or "").upper() in ("COMPLETED", "PARTIAL_FAILED", "SUCCESS", "DONE")]
    checks["boardCompletedTasksCount"] = len(completed)
    assert st == 200 and len(completed) > 0, "No completed tasks found on /api/detection/board"
    sample_task_id = str(completed[0].get("taskId") or completed[0].get("id"))

    # 2. Cross-role report draft -> idempotency check -> submit -> supervisor decision-preview -> employee withdraw
    hdrs = {"X-Report-Action": "update"}
    req_id = str(uuid.uuid4())
    payload = {"taskId": sample_task_id, "title": "90+联调核验草稿(自动撤回)", "narrative": "双角色闭环实测验证意见", "requestId": req_id}
    st1, r1 = call_json(det, "POST", "/api/detection/reports", payload, hdrs)
    st2, r2 = call_json(det, "POST", "/api/detection/reports", payload, hdrs)
    assert st1 == 200 and r1.get("code") == 200, f"draft create failed: {st1} {r1}"
    report_id = r1["data"]["reportId"]
    version = r1["data"]["version"]
    checks["reportDraftIdempotent"] = (st2 == 200 and r2.get("data", {}).get("reportId") == report_id)

    st_sub, r_sub = call_json(det, "POST", f"/api/detection/reports/{report_id}/submit", {"expectedVersion": version, "requestId": str(uuid.uuid4())}, hdrs)
    assert st_sub == 200 and r_sub.get("code") == 200, f"submit failed: {st_sub} {r_sub}"
    sub_version = r_sub["data"]["version"]

    st_prev, r_prev = call_json(sup, "POST", f"/api/detection/reports/{report_id}/decision-preview", {"expectedVersion": sub_version, "decision": "APPROVE", "reason": "双角色预览核验"}, hdrs)
    checks["supervisorDecisionPreviewPass"] = (st_prev == 200 and r_prev.get("code") == 200 and bool(r_prev.get("data", {}).get("confirmationToken")))

    st_wd, r_wd = call_json(det, "POST", f"/api/detection/reports/{report_id}/withdraw", {"expectedVersion": sub_version, "requestId": str(uuid.uuid4())}, hdrs)
    checks["employeeWithdrawClean"] = (st_wd == 200 and r_wd.get("code") == 200)

    # 3. Role & private chat isolation
    st_forbid, _ = call_json(det, "GET", "/api/detection/supervisor/work-units/pending")
    checks["employeeBlockedFromSupervisorQueue"] = (st_forbid in (401, 403))

    st_sup_s, sup_s = call_json(sup, "GET", "/api/chat-assistant/sessions")
    sup_sid = (sup_s.get("data") or [{}])[0].get("sessionId")
    if sup_sid:
        st_cross1, b_cross1 = call_json(det, "GET", f"/api/chat-assistant/sessions/{sup_sid}")
        checks["employeeBlockedFromSupervisorChat"] = (st_cross1 in (403, 404) or b_cross1.get("code") in (403, 404))

    st_det_s, det_s = call_json(det, "GET", "/api/chat-assistant/sessions")
    det_sid = (det_s.get("data") or [{}])[0].get("sessionId")
    if det_sid:
        st_cross2, b_cross2 = call_json(sup, "GET", f"/api/chat-assistant/sessions/{det_sid}")
        checks["supervisorBlockedFromEmployeeChat"] = (st_cross2 in (403, 404) or b_cross2.get("code") in (403, 404))

    return checks


def main():
    report = {
        "writeTps": benchmark_write_tps(),
        "bulkheadIsolation": benchmark_bulkhead_isolation(),
        "twoRoleE2E": verify_two_role_e2e(),
    }
    out = Path("work/reviews/write-tps-and-e2e-result.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
