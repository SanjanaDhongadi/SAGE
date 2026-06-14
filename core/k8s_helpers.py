"""Kubernetes: phases, pod names, discovery, and live utilization via kubectl top."""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import time
from typing import Any

from core.sage_config import K8S_NAMESPACE

_LOG = logging.getLogger(__name__)

_top_cache: dict[str, tuple[float, float, float]] = {}
_TOP_TTL_SEC = 5.0


def get_pod_phase_for_app(app_name: str, namespace: str = K8S_NAMESPACE, timeout: int = 8) -> str:
    """
    Return a single phase for pods with label app=<app_name>.
    Prefer Running if any replica is Running.
    """
    try:
        r = subprocess.run(
            [
                "kubectl",
                "get",
                "pods",
                "-l",
                f"app={app_name}",
                "-n",
                namespace,
                "-o",
                "jsonpath={.items[*].status.phase}",
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if r.returncode != 0:
            err = (r.stderr or r.stdout or "").strip()
            if err:
                _LOG.debug("kubectl get pods failed for app=%s: %s", app_name, err[:200])
            return "Unknown"
        phases = [p.strip() for p in r.stdout.split() if p.strip()]
        if not phases:
            return "Unknown"
        if any(p == "Running" for p in phases):
            return "Running"
        if any(p == "Failed" for p in phases):
            return "Failed"
        if any(p in ("Pending", "ContainerCreating", "PodInitializing") for p in phases):
            return "Pending"
        return phases[0]
    except Exception as e:
        _LOG.debug("get_pod_phase_for_app(%s): %s", app_name, e)
        return "Unknown"


def list_pod_names_for_app(app_name: str, namespace: str = K8S_NAMESPACE, timeout: int = 8) -> list[str]:
    """All pod names for label app=<app_name> (Prometheus matchers + kubectl top)."""
    try:
        r = subprocess.run(
            [
                "kubectl",
                "get",
                "pods",
                "-l",
                f"app={app_name}",
                "-n",
                namespace,
                "-o",
                "jsonpath={.items[*].metadata.name}",
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if r.returncode != 0 or not r.stdout.strip():
            return []
        return [n.strip() for n in r.stdout.split() if n.strip()]
    except Exception as e:
        _LOG.debug("list_pod_names_for_app(%s): %s", app_name, e)
        return []


def resolve_running_pod_name(app_name: str, namespace: str = K8S_NAMESPACE, timeout: int = 8) -> str | None:
    """Return a Running pod name for label app=<app_name>, else first pod name, else None."""
    names = list_pod_names_for_app(app_name, namespace, timeout=timeout)
    for name in names:
        pr = subprocess.run(
            ["kubectl", "get", "pod", name, "-n", namespace, "-o", "jsonpath={.status.phase}"],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if pr.stdout.strip() == "Running":
            return name
    return names[0] if names else None


def kubectl_json(args: list[str], timeout: int = 20) -> dict[str, Any] | None:
    """Run kubectl with -o json and parse JSON."""
    try:
        r = subprocess.run(
            ["kubectl", *args, "-o", "json"],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if r.returncode != 0:
            return None
        return json.loads(r.stdout or "{}")
    except Exception as e:
        _LOG.debug("kubectl_json failed: %s", e)
        return None


def list_deployments(namespace: str = K8S_NAMESPACE, timeout: int = 20) -> list[dict[str, Any]]:
    doc = kubectl_json(["get", "deployments", "-n", namespace], timeout=timeout)
    if not doc:
        return []
    return list(doc.get("items") or [])


def list_pods(namespace: str = K8S_NAMESPACE, timeout: int = 20) -> list[dict[str, Any]]:
    doc = kubectl_json(["get", "pods", "-n", namespace], timeout=timeout)
    if not doc:
        return []
    return list(doc.get("items") or [])


def discover_logical_workloads(namespace: str | None = None) -> list[str]:
    """
    Deployment names for the SAGE demo fleet (prefixes from SAGE_WORKLOAD_PREFIXES).
    Kept here (single place) instead of a separate discovery module.
    """
    ns = namespace or K8S_NAMESPACE
    raw = os.environ.get("SAGE_WORKLOAD_PREFIXES", "web-app,flask-app")
    prefixes = tuple(p.strip() for p in raw.split(",") if p.strip()) or ("web-app", "flask-app")
    out: list[str] = []
    for item in list_deployments(ns):
        meta = item.get("metadata") or {}
        name = str(meta.get("name") or "")
        if not name:
            continue
        if not any(name.startswith(p + "-") or name == p for p in prefixes):
            continue
        if re.search(r"-\d+$", name):
            out.append(name)
    out = sorted(set(out), key=lambda s: (s.split("-")[0], int(s.rsplit("-", 1)[-1])))
    if not out:
        _LOG.warning("[discovery] no deployments matched prefixes=%s ns=%s", prefixes, ns)
    return out


def _parse_cpu_quantity(q: str) -> float:
    """Kubernetes CPU quantity or kubectl top CPU cell → cores (float)."""
    q = str(q).strip()
    if not q:
        return 0.0
    if q.endswith("m"):
        return float(q[:-1]) / 1000.0
    if q.endswith("n"):
        return float(q[:-1]) / 1e9
    return float(q)


def _parse_mem_quantity(q: str) -> float:
    """Kubernetes memory quantity or kubectl top MEM cell → bytes."""
    q = str(q).strip()
    if not q:
        return 0.0
    for suf, mult in (("Ki", 1024), ("Mi", 1024**2), ("Gi", 1024**3), ("Ti", 1024**4)):
        if q.endswith(suf):
            return float(q[: -len(suf)]) * mult
    if q.isdigit():
        return float(q)
    q_up = q.upper()
    for suf, mult in (("K", 1000), ("M", 1000**2), ("G", 1000**3), ("T", 1000**4)):
        if q_up.endswith(suf) and not q_up.endswith("I"):
            return float(q_up[: -len(suf)]) * mult
    try:
        return float(q)
    except ValueError:
        return 0.0


def _pod_limits_cpu_mem_bytes(pod_name: str, namespace: str) -> tuple[float, float]:
    """Sum limits.cpu and limits.memory across containers; fall back to requests."""
    doc = kubectl_json(["get", "pod", pod_name, "-n", namespace])
    if not doc:
        return 0.1, float(256 * 1024 * 1024)
    cpu_cores = 0.0
    mem_bytes = 0.0
    for c in (doc.get("spec") or {}).get("containers") or []:
        res = c.get("resources") or {}
        lim = res.get("limits") or {}
        req = res.get("requests") or {}
        cpu_s = lim.get("cpu") or req.get("cpu") or "100m"
        mem_s = lim.get("memory") or req.get("memory") or "256Mi"
        cpu_cores += _parse_cpu_quantity(str(cpu_s))
        mem_bytes += _parse_mem_quantity(str(mem_s))
    return max(cpu_cores, 1e-6), max(mem_bytes, 1.0)


def kubectl_top_pod_cpu_mem_percent(logical_app: str, namespace: str = K8S_NAMESPACE) -> tuple[float, float] | None:
    """
    CPU% and mem% of pod limits using `kubectl top pod` + pod spec limits (metrics-server).
    Cached briefly because monitoring calls CPU and mem separately.
    """
    cache_key = f"{namespace}::{logical_app}"
    now = time.time()
    hit = _top_cache.get(cache_key)
    if hit and (now - hit[2]) <= _TOP_TTL_SEC:
        return hit[0], hit[1]

    pod = resolve_running_pod_name(logical_app, namespace)
    if not pod:
        names = list_pod_names_for_app(logical_app, namespace)
        pod = names[0] if names else None
    if not pod:
        return None

    r = subprocess.run(
        ["kubectl", "top", "pod", pod, "-n", namespace, "--no-headers"],
        capture_output=True,
        text=True,
        timeout=15,
    )
    if r.returncode != 0 or not (r.stdout or "").strip():
        _LOG.debug("kubectl top pod failed for %s: %s", pod, (r.stderr or "").strip()[:160])
        return None

    parts = r.stdout.strip().splitlines()[0].split()
    if len(parts) < 3:
        return None
    used_cpu = _parse_cpu_quantity(parts[1])
    used_mem = _parse_mem_quantity(parts[2])
    lim_cpu, lim_mem = _pod_limits_cpu_mem_bytes(pod, namespace)
    cpu_pct = 100.0 * used_cpu / lim_cpu
    mem_pct = 100.0 * used_mem / lim_mem
    cpu_pct = float(min(max(cpu_pct, 0.0), 500.0))
    mem_pct = float(min(max(mem_pct, 0.0), 500.0))
    _top_cache[cache_key] = (cpu_pct, mem_pct, now)
    return cpu_pct, mem_pct
