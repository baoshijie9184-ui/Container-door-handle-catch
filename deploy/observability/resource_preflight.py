"""ECS-only, read-only resource gate. Run before image pull, never purchases resources."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import shutil

GIB = 1024 ** 3
BUDGETS = {
    "production": {"total_memory": 32 * GIB, "available_memory": 24 * GIB, "free_disk": 30 * GIB},
    "isolated-smoke": {"total_memory": 8 * GIB, "available_memory": 6 * GIB, "free_disk": 12 * GIB},
}

def decide(mode: str, approved: str, total: int, available: int, free: int, business_reserve: int) -> dict:
    if mode not in BUDGETS or business_reserve < 0:
        raise ValueError("OBSERVABILITY_PREFLIGHT_INPUT_INVALID")
    required = dict(BUDGETS[mode])
    required["free_disk"] += business_reserve
    failed = []
    if approved != mode + "-reviewed":
        failed.append("approval")
    for name, value in (("total_memory", total), ("available_memory", available), ("free_disk", free)):
        if value < required[name]:
            failed.append(name)
    return {"schemaVersion": 1, "mode": mode, "status": "PASS" if not failed else "BLOCKED",
            "failedGates": failed, "requiredBytes": required,
            "observedBytes": {"total_memory": total, "available_memory": available, "free_disk": free},
            "businessReserveBytes": business_reserve,
            "productionCapacityVerified": False}

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=sorted(BUDGETS), default="production")
    parser.add_argument("--data-root", required=True)
    parser.add_argument("--business-reserve-gib", type=float, required=True)
    parser.add_argument("--receipt", required=True)
    args = parser.parse_args()
    if os.name != "posix" or not Path("/proc/meminfo").is_file():
        raise SystemExit("OBSERVABILITY_PREFLIGHT_REQUIRES_ECS_LINUX")
    memory = {}
    for line in Path("/proc/meminfo").read_text(encoding="ascii").splitlines():
        key, value = line.split(":", 1)
        memory[key] = int(value.strip().split()[0]) * 1024
    reserve = int(args.business_reserve_gib * GIB)
    receipt = decide(args.mode, os.environ.get("LANGFUSE_RESOURCE_APPROVED", ""),
                     memory["MemTotal"], memory["MemAvailable"], shutil.disk_usage(args.data_root).free, reserve)
    path = Path(args.receipt)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("OBSERVABILITY_PREFLIGHT_" + receipt["status"])
    return 0 if receipt["status"] == "PASS" else 42

if __name__ == "__main__":
    raise SystemExit(main())
