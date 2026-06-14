from __future__ import annotations

import os
import requests


def p(msg: str) -> None:
    print(msg)


def check_prometheus(prom_url: str) -> bool:
    ok = True
    try:
        r = requests.get(f"{prom_url}/api/v1/targets", timeout=8)
        r.raise_for_status()
        active = r.json().get("data", {}).get("activeTargets", [])
        up = [t for t in active if t.get("health") == "up"]
        p(f"Prometheus active targets: {len(active)} | UP: {len(up)}")
        if not up:
            ok = False
    except Exception as e:
        p(f"FAIL Prometheus targets query: {e}")
        return False

    checks = [
        "up",
        "kube_pod_info",
        "kube_node_info",
        "container_cpu_usage_seconds_total",
    ]
    for q in checks:
        try:
            r = requests.get(f"{prom_url}/api/v1/query", params={"query": q}, timeout=8)
            r.raise_for_status()
            n = len(r.json().get("data", {}).get("result", []))
            p(f"PromQL `{q}` -> {n} series")
            if n == 0:
                ok = False
        except Exception as e:
            p(f"FAIL PromQL `{q}`: {e}")
            ok = False
    return ok


def check_grafana(grafana_url: str) -> bool:
    try:
        r = requests.get(f"{grafana_url}/api/health", timeout=8)
        if r.status_code == 401:
            p("Grafana reachable (health endpoint requires auth).")
            return True
        r.raise_for_status()
        p(f"Grafana health: {r.json()}")
        return True
    except Exception as e:
        p(f"FAIL Grafana health check: {e}")
        return False


def main() -> int:
    prom_url = os.environ.get("SAGE_PROMETHEUS_URL", "http://127.0.0.1:9090")
    grafana_url = os.environ.get("SAGE_GRAFANA_URL", "http://127.0.0.1:3000")
    p(f"Checking Prometheus at {prom_url}")
    prom_ok = check_prometheus(prom_url)
    p(f"\nChecking Grafana at {grafana_url}")
    graf_ok = check_grafana(grafana_url)

    if prom_ok and graf_ok:
        p("\nPASS monitoring stack connectivity verified.")
        return 0
    p("\nFAIL monitoring stack has connectivity/issues.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
