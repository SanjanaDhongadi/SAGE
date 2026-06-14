from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any

from core import runtime_state as rt
from core.sage_config import AGENT_EVENTS_JSONL_PATH, EVENTS_JSONL_PATH, MEMORY_PATH, UI_STATUS_PATH


def _read_json(path: str) -> dict[str, Any]:
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _tail_jsonl(path: str, limit: int = 20) -> list[dict[str, Any]]:
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()[-limit:]
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
            # Ignore partial/truncated tail lines while writer appends.
            continue
    return out


def write_ui_snapshot() -> None:
    incidents_doc = _read_json(str(MEMORY_PATH))
    incidents = incidents_doc.get("incidents") if isinstance(incidents_doc, dict) else []
    if not isinstance(incidents, list):
        incidents = []
    recent_incidents = incidents[-12:]

    payload = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "sla_states": rt.snapshot_sla_states(),
        "metrics": rt.snapshot_metrics(),
        "counters": rt.snapshot_counters(),
        "last_injector_event": rt.get_last_injector_event(),
        "recent_incidents": recent_incidents,
        "recent_events": _tail_jsonl(str(EVENTS_JSONL_PATH), 40),
        "agent_events": _tail_jsonl(str(AGENT_EVENTS_JSONL_PATH), 120),
    }

    os.makedirs(os.path.dirname(str(UI_STATUS_PATH)), exist_ok=True)
    tmp = str(UI_STATUS_PATH) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    os.replace(tmp, str(UI_STATUS_PATH))
