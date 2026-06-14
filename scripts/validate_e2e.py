from __future__ import annotations

import json
import os
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"


def check_file(path: Path) -> tuple[bool, str]:
    if not path.exists():
        return False, f"missing: {path}"
    if path.stat().st_size == 0:
        return False, f"empty: {path}"
    return True, f"ok: {path.name}"


def prom_query(base: str, q: str) -> tuple[bool, str]:
    try:
        r = requests.get(
            f"{base}/api/v1/query",
            params={"query": q},
            timeout=8,
        )
        r.raise_for_status()
        data = r.json().get("data", {}).get("result", [])
        return True, f"{q} -> {len(data)} series"
    except Exception as e:
        return False, f"{q} failed: {e}"


def main() -> int:
    checks: list[tuple[bool, str]] = []
    checks.append(check_file(DATA / "ui_status.json"))
    checks.append(check_file(DATA / "episodic_memory.json"))
    checks.append(check_file(DATA / "sage_events.jsonl"))
    checks.append(check_file(DATA / "remediation_log.xlsx"))
    checks.append(check_file(DATA / "stress_log.xlsx"))

    prom = os.environ.get("SAGE_PROMETHEUS_URL", "http://127.0.0.1:9090")
    checks.append(prom_query(prom, "up"))
    checks.append(prom_query(prom, "sage_pod_breach_probability"))
    checks.append(prom_query(prom, "kube_pod_container_status_restarts_total"))

    exporter = os.environ.get("SAGE_EXPORTER_URL", "http://127.0.0.1:9108/metrics")
    try:
        resp = requests.get(exporter, timeout=5)
        ok = resp.ok and "sage_pod_breach_probability" in resp.text
        checks.append((ok, f"exporter {exporter} {'ok' if ok else 'missing expected metric'}"))
    except Exception as e:
        checks.append((False, f"exporter check failed: {e}"))

    ui_path = DATA / "ui_status.json"
    try:
        payload = json.loads(ui_path.read_text(encoding="utf-8"))
        ok = "metrics" in payload and "sla_states" in payload
        checks.append((ok, "ui_status schema valid" if ok else "ui_status schema invalid"))
    except Exception as e:
        checks.append((False, f"ui_status parse failed: {e}"))

    failed = [msg for ok, msg in checks if not ok]
    for ok, msg in checks:
        print(("PASS " if ok else "FAIL ") + msg)
    if failed:
        print("\nE2E validation failed.")
        return 1
    print("\nE2E validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
