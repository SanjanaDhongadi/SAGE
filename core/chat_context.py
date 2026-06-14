"""Assemble multi-source retrieval context for the operational chatbot."""
from __future__ import annotations

import json
import os
import re
from datetime import datetime
from typing import Any

import openpyxl

from core import incident_memory as im
from core import runtime_state as rt
from core.k8s_helpers import kubectl_json, list_pod_names_for_app
from core.prometheus_client import PROMETHEUS_URL, query_range, validate_pod_metrics
from core.sage_config import (
    EVENTS_JSONL_PATH,
    K8S_NAMESPACE,
    REMED_LOG_PATH,
    STRESS_LOG_PATH,
)


def _kubectl_summary(namespace: str = K8S_NAMESPACE) -> str:
    pods_doc = kubectl_json(["get", "pods", "-n", namespace])
    dep_doc = kubectl_json(["get", "deployments", "-n", namespace])
    lines: list[str] = []
    lines.append(f"Kubernetes namespace: {namespace}")
    if dep_doc:
        items = dep_doc.get("items") or []
        lines.append(f"Deployments ({len(items)}):")
        for it in items[:30]:
            meta = it.get("metadata") or {}
            spec = it.get("spec") or {}
            st = it.get("status") or {}
            name = meta.get("name", "")
            rep = spec.get("replicas")
            ready = st.get("readyReplicas")
            lines.append(f"  - {name}: replicas={rep} ready={ready}")
    if pods_doc:
        items = pods_doc.get("items") or []
        running = sum(1 for it in items if (it.get("status") or {}).get("phase") == "Running")
        lines.append(f"Pods: total={len(items)} running={running}")
        for it in items[:25]:
            meta = it.get("metadata") or {}
            name = meta.get("name", "")
            phase = (it.get("status") or {}).get("phase", "")
            lines.append(f"  - {name}: {phase}")
    if len(lines) == 1:
        lines.append("(kubectl JSON unavailable — check kubeconfig/context)")
    return "\n".join(lines)


def _tail_xlsx(path: str, max_rows: int = 25) -> str:
    p = str(path)
    if not os.path.exists(p):
        return f"(missing file: {p})"
    try:
        wb = openpyxl.load_workbook(p, read_only=True)
        ws = wb.active
        rows = list(ws.iter_rows(values_only=True))
    except Exception as e:
        return f"(could not read {p}: {e})"
    if not rows:
        return "(empty workbook)"
    tail = rows[-max_rows:]
    out = [", ".join(str(c) if c is not None else "" for c in tail[0])]
    for r in tail[1:]:
        out.append(", ".join(str(c) if c is not None else "" for c in r))
    return "\n".join(out)


def _prometheus_snippet(pod_hint: str | None) -> str:
    """Small range snippets for chat evidence (not full Grafana charts)."""
    end = datetime.now().timestamp()
    start = end - 3600
    lines: list[str] = []
    lines.append(f"Prometheus: {PROMETHEUS_URL}")
    if not pod_hint:
        return "\n".join(lines)

    diag: dict[str, Any] = {}
    try:
        diag = validate_pod_metrics(pod_hint)
        lines.append(
            "Metric diagnostics: "
            + json.dumps(diag, default=str)[:1200]
        )
    except Exception as e:
        lines.append(f"Metric diagnostics failed: {e}")

    pod_re = str(diag.get("pod_regex") or "")
    if not pod_re:
        names = list_pod_names_for_app(pod_hint, K8S_NAMESPACE)
        if names:
            inner = "|".join(re.escape(n) for n in names)
            pod_re = f"^({inner})$"
    if not pod_re:
        lines.append("Could not build pod regex (no kubectl pod names).")
        return "\n".join(lines)

    q = (
        f'sum(rate(container_cpu_usage_seconds_total{{namespace="{K8S_NAMESPACE}",'
        f'pod=~"{pod_re}",container!="",container!="POD"}}[5m]))'
    )
    series = query_range(q, start, end, step=60)
    if series:
        vals = series[0].get("values") or []
        tail = vals[-6:]
        lines.append(f"Last hour CPU rate (cores/sec aggregated): {tail}")
    else:
        lines.append("Last hour CPU range query returned no series.")
    return "\n".join(lines)


def build_operational_context(user_question: str) -> str:
    hints = im.extract_pod_hints(user_question)
    pod_hint = hints[0] if hints else None

    blocks: list[str] = []
    blocks.append("=== LIVE CLUSTER (kubectl) ===\n" + _kubectl_summary())

    blocks.append("=== MONITORING RUNTIME SNAPSHOT (SAGE in-process) ===")
    blocks.append(json.dumps(rt.snapshot_sla_states(), indent=2, sort_keys=True)[:4000])
    blocks.append(json.dumps(rt.snapshot_metrics(), indent=2, sort_keys=True)[:8000])

    blocks.append("=== LAST INJECTOR EVENT (SAGE in-process) ===")
    blocks.append(json.dumps(rt.get_last_injector_event(), indent=2, default=str))

    blocks.append("=== INJECTOR / STRESS JSONL (tail) ===")
    blocks.append(json.dumps(im.tail_jsonl(str(EVENTS_JSONL_PATH), 25), indent=2)[:8000])

    blocks.append("=== STRESS XLSX (tail) ===\n" + _tail_xlsx(STRESS_LOG_PATH))

    blocks.append("=== REMEDIATION XLSX (tail) ===\n" + _tail_xlsx(REMED_LOG_PATH))

    blocks.append("=== EPISODIC MEMORY RETRIEVAL (ranked) ===")
    ranked = im.search_incidents_natural_language(user_question, pod_hint=pod_hint, top_k=6)
    blocks.append(json.dumps(ranked, indent=2, default=str)[:12000])

    blocks.append("=== PROMETHEUS EVIDENCE ===\n" + _prometheus_snippet(pod_hint))

    blocks.append(
        "Instructions: answer ONLY using the sections above. "
        "If something is missing/unavailable, say what is missing and what you can still conclude."
    )
    return "\n\n".join(blocks)
