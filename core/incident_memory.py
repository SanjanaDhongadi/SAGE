"""
Episodic incident memory for SAGE (dynamic, retrieval-friendly).

Stores rich incidents and supports:
- cosine similarity on numeric feature snapshots (recurring incident matching)
- lightweight "semantic" retrieval via token overlap on narrative text + pod filters
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from datetime import datetime
from typing import Any

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from core.sage_config import MEMORY_PATH

_LOG = logging.getLogger(__name__)

MEMORY_PATH_STR = str(MEMORY_PATH)
SIMILARITY_THRESHOLD = float(os.environ.get("SAGE_MEMORY_SIM_THRESHOLD", "0.78"))
_MAX_INCIDENTS = int(os.environ.get("SAGE_MEMORY_MAX", "800"))


def _load_file() -> dict[str, Any]:
    if not os.path.exists(MEMORY_PATH_STR):
        return {"schema": 2, "incidents": []}
    with open(MEMORY_PATH_STR, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_file(data: dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(MEMORY_PATH_STR), exist_ok=True)
    tmp = MEMORY_PATH_STR + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, MEMORY_PATH_STR)


def _incidents_list(data: dict[str, Any]) -> list[dict[str, Any]]:
    if isinstance(data.get("incidents"), list):
        return list(data["incidents"])
    # legacy episodic_memory.json shape
    if isinstance(data.get("episodes"), list):
        return list(data["episodes"])
    return []


def _narrative(inc: dict[str, Any]) -> str:
    parts = [
        str(inc.get("pod", "")),
        str(inc.get("timestamp", "")),
        f"breach {inc.get('breach_prob_before')}",
        f"cpu {inc.get('cpu_percent')}",
        f"mem {inc.get('mem_percent')}",
        str(inc.get("injector_event", "")),
        str(inc.get("root_cause", "")),
        str(inc.get("action_taken", "")),
        str(inc.get("outcome", "")),
        str(inc.get("recovery_time_seconds", "")),
    ]
    return " ".join(p for p in parts if p and p != "None")


def find_similar(features: dict[str, Any]) -> dict[str, Any] | None:
    """Best incident match using cosine similarity on the shared numeric snapshot."""
    data = _load_file()
    incidents = _incidents_list(data)
    if not incidents:
        return None
    q_keys = sorted(features.keys())
    q = np.array([float(features.get(k, 0.0)) for k in q_keys], dtype=float).reshape(1, -1)
    best_score, best = 0.0, None
    for inc in incidents:
        snap = inc.get("features_snapshot") or {}
        if not snap:
            continue
        keys = sorted(snap.keys())
        v = np.array([float(snap.get(k, 0.0)) for k in keys], dtype=float).reshape(1, -1)
        if q.shape[1] != v.shape[1]:
            # align by intersection for backwards compatibility
            common = sorted(set(q_keys) & set(keys))
            if len(common) < 3:
                continue
            q2 = np.array([[float(features.get(k, 0.0)) for k in common]], dtype=float)
            v2 = np.array([[float(snap.get(k, 0.0)) for k in common]], dtype=float)
        else:
            q2, v2 = q, v
        score = float(cosine_similarity(q2, v2)[0][0])
        if score > best_score:
            best_score, best = score, inc
    return best if best_score >= SIMILARITY_THRESHOLD else None


def search_incidents_natural_language(
    query: str,
    *,
    pod_hint: str | None = None,
    top_k: int = 6,
) -> list[dict[str, Any]]:
    """
    Lightweight semantic-ish retrieval:
    TF-IDF cosine between query and precomputed narratives, boosted by pod substring matches.
    """
    incidents = _incidents_list(_load_file())
    if not incidents:
        return []
    narratives = [_narrative(i) for i in incidents]
    sims = np.zeros(len(incidents))
    try:
        if len(narratives) >= 2:
            vec = TfidfVectorizer(stop_words="english", max_features=4096)
            X = vec.fit_transform([query] + narratives)
            sims = cosine_similarity(X[0:1], X[1:]).ravel()
        elif len(narratives) == 1:
            # Degenerate corpus: fall back to token overlap only
            sims = np.array([0.12])
    except Exception as e:
        _LOG.debug("TF-IDF retrieval degraded: %s", e)
        sims = np.zeros(len(incidents))

    ranked: list[tuple[float, dict[str, Any]]] = []
    q_low = query.lower()
    for idx, inc in enumerate(incidents):
        score = float(sims[idx]) if idx < len(sims) else 0.0
        pod = str(inc.get("pod", ""))
        if pod_hint and pod_hint in pod:
            score += 0.35
        if pod and pod.lower() in q_low:
            score += 0.25
        # keyword boosts
        for kw in ("cpu", "memory", "stress", "inject", "remed", "breach", "flask", "web-app"):
            if kw in q_low and kw in _narrative(inc).lower():
                score += 0.05
        ranked.append((score, inc))
    ranked.sort(key=lambda t: t[0], reverse=True)
    return [inc for s, inc in ranked[:top_k] if s > 0.01]


def store_incident(incident: dict[str, Any]) -> dict[str, Any]:
    """Persist a normalized incident (dynamic append)."""
    data = _load_file()
    incidents = _incidents_list(data)
    incident.setdefault("id", f"inc_{len(incidents) + 1:05d}")
    incident.setdefault("timestamp", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    incident.setdefault("narrative", _narrative(incident))
    incidents.append(incident)
    if len(incidents) > _MAX_INCIDENTS:
        incidents = incidents[-_MAX_INCIDENTS:]
    data["schema"] = 2
    data["incidents"] = incidents
    if "episodes" in data:
        del data["episodes"]
    _save_file(data)
    return incident


def store_from_remediation_pipeline(episode: dict[str, Any]) -> dict[str, Any]:
    """Adapter for remediation_agent.store_episode(...) payloads."""
    snap = episode.get("features_snapshot") or {}
    inc = {
        "pod": episode.get("pod"),
        "deployment": episode.get("deployment"),
        "trigger_state": episode.get("trigger_state"),
        "cpu_percent": float(snap.get("cpu_util_percent", 0.0)),
        "mem_percent": float(snap.get("mem_util_percent", 0.0)),
        "breach_prob_before": float(episode.get("breach_prob_before", 0.0)),
        "breach_prob_after": float(episode.get("breach_prob_after", 0.0)),
        "injector_event": episode.get("injector_event") or episode.get("injector_context"),
        "stress_type_detected": episode.get("stress_type_detected"),
        "features_snapshot": snap,
        "root_cause": episode.get("root_cause"),
        "llm_reasoning": episode.get("llm_reasoning"),
        "action_taken": episode.get("action_taken"),
        "outcome": episode.get("outcome"),
        "recovery_time_seconds": episode.get("recovery_time_seconds"),
        "priority": episode.get("priority")
        or {
            "CRASHED": "high",
            "CRITICAL": "medium",
            "WARNING": "low",
        }.get(str(episode.get("trigger_state") or "WARNING"), "low"),
    }
    return store_incident(inc)


def append_injector_event(
    logical_pod: str,
    stress_type: str,
    duration: int,
    reasoning: str,
    events_path: str,
) -> None:
    """Append-only JSONL for Grafana/Loki-style pipelines and chatbot retrieval."""
    os.makedirs(os.path.dirname(events_path), exist_ok=True)
    row = {
        "ts": time.time(),
        "iso": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "type": "injector",
        "logical_pod": logical_pod,
        "stress_type": stress_type,
        "duration_seconds": duration,
        "reasoning": reasoning,
    }
    with open(events_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def tail_jsonl(path: str, max_lines: int = 40) -> list[dict[str, Any]]:
    if not os.path.exists(path):
        return []
    lines: list[str] = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()[-max_lines:]
    except Exception:
        return []
    out: list[dict[str, Any]] = []
    for ln in lines:
        ln = ln.strip()
        if not ln:
            continue
        try:
            out.append(json.loads(ln))
        except Exception:
            continue
    return out


def extract_pod_hints(text: str) -> list[str]:
    return sorted(
        set(
            m.group(0)
            for m in re.finditer(r"\b(?:web-app|flask-app)-\d+\b", text, flags=re.IGNORECASE)
        )
    )
