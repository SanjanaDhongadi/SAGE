"""Cross-agent runtime state (pod SLA state, remediation UI hints, live metric snapshots)."""
from __future__ import annotations

import threading
import time
from collections import defaultdict

_lock = threading.RLock()
_pod_states: dict[str, str] = defaultdict(lambda: "HEALTHY")
_remediation_status: dict[str, str] = defaultdict(lambda: "—")
_pod_metrics: dict[str, dict[str, float]] = {}
_counters = {"remediation_completed": 0, "injector_events": 0}
_last_injector: dict[str, str | float | int] = {}


def set_pod_state(pod: str, state: str) -> None:
    with _lock:
        _pod_states[pod] = state


def get_pod_state(pod: str) -> str:
    with _lock:
        return _pod_states.get(pod, "HEALTHY")


def set_remediation_status(pod: str, status: str) -> None:
    with _lock:
        _remediation_status[pod] = status


def get_remediation_status(pod: str) -> str:
    with _lock:
        return _remediation_status.get(pod, "—")


def record_pod_metrics_snapshot(
    pod: str, cpu: float, mem: float, breach: float, ttb: float
) -> None:
    with _lock:
        _pod_metrics[pod] = {
            "cpu_percent": float(cpu),
            "mem_percent": float(mem),
            "breach_prob": float(breach),
            "ttb_seconds": float(ttb),
            "ts": time.time(),
        }


def snapshot_metrics() -> dict[str, dict[str, float]]:
    with _lock:
        return {k: dict(v) for k, v in _pod_metrics.items()}


def snapshot_sla_states() -> dict[str, str]:
    with _lock:
        return dict(_pod_states)


def record_last_injector_event(
    logical_pod: str, stress_type: str, duration: int, reasoning: str
) -> None:
    with _lock:
        _last_injector.update(
            {
                "logical_pod": logical_pod,
                "stress_type": stress_type,
                "duration_seconds": duration,
                "reasoning": reasoning,
                "ts": time.time(),
            }
        )


def get_last_injector_event() -> dict[str, str | float | int]:
    with _lock:
        return dict(_last_injector)


def bump_remediation_completed() -> None:
    with _lock:
        _counters["remediation_completed"] += 1


def bump_injector_events() -> None:
    with _lock:
        _counters["injector_events"] += 1


def snapshot_counters() -> dict[str, int]:
    with _lock:
        return dict(_counters)
