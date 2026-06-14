"""Central configuration for SAGE (paths, LLM, intervals, limits)."""
from __future__ import annotations

import os
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
SAGE_ROOT = Path(os.environ.get("SAGE_ROOT", str(_ROOT))).resolve()

MODELS_DIR = SAGE_ROOT / "models"
DATA_DIR = SAGE_ROOT / "data"

CLF_PATH = Path(os.environ.get("SAGE_CLF_PATH", str(MODELS_DIR / "clf_breach_probability.pkl")))
REG_PATH = Path(os.environ.get("SAGE_REG_PATH", str(MODELS_DIR / "reg_time_to_breach.pkl")))
REMED_LOG_PATH = Path(os.environ.get("SAGE_REMED_LOG", str(DATA_DIR / "remediation_log.xlsx")))
STRESS_LOG_PATH = Path(os.environ.get("SAGE_STRESS_LOG", str(DATA_DIR / "stress_log.xlsx")))
MEMORY_PATH = Path(os.environ.get("SAGE_MEMORY_PATH", str(DATA_DIR / "episodic_memory.json")))

# Groq / LangChain ChatGroq uses `model` kwarg
GROQ_MODEL = os.environ.get("SAGE_GROQ_MODEL", "llama-3.1-8b-instant")
GROQ_FALLBACK_MODELS = [
    m.strip()
    for m in os.environ.get(
        "SAGE_GROQ_MODEL_FALLBACKS",
        "llama-3.3-70b-versatile,mixtral-8x7b-32768",
    ).split(",")
    if m.strip()
]

DEBUG = os.environ.get("SAGE_DEBUG", "").lower() in ("1", "true", "yes")

# Monitoring dashboard
MONITOR_REFRESH_SECONDS = float(os.environ.get("SAGE_MONITOR_REFRESH", "20"))
LIVE_REFRESH_PER_SECOND = float(os.environ.get("SAGE_LIVE_RPS", "0.15"))

# Remediation queue / worker
REMEDIATION_QUEUE_MAX = int(os.environ.get("SAGE_REMEDIATION_QUEUE_MAX", "32"))
REMEDIATION_MAX_RETRIES = int(os.environ.get("SAGE_REMEDIATION_LLM_RETRIES", "3"))
REMEDIATION_LLM_RETRY_DELAY = float(os.environ.get("SAGE_REMEDIATION_LLM_RETRY_DELAY", "2.0"))
VERIFY_WAIT_SECONDS = float(os.environ.get("SAGE_VERIFY_SECONDS", "90"))

# Injector (demo-friendly defaults)
INJECTOR_BASE_INTERVAL = float(os.environ.get("SAGE_INJECTOR_INTERVAL_BASE", "180"))
INJECTOR_JITTER = float(os.environ.get("SAGE_INJECTOR_JITTER", "120"))
INJECTOR_COOLDOWN_PER_POD = float(os.environ.get("SAGE_INJECTOR_POD_COOLDOWN", "300"))
INJECTOR_INTENSITY = int(os.environ.get("SAGE_INJECTOR_INTENSITY", "2"))  # 1=mild, 2=normal, 3=strong
INJECTOR_USE_LLM = os.environ.get("SAGE_INJECTOR_USE_LLM", "0").lower() in ("1", "true", "yes")

K8S_NAMESPACE = os.environ.get("SAGE_K8S_NAMESPACE", "default")

EVENTS_JSONL_PATH = Path(
    os.environ.get("SAGE_EVENTS_JSONL", str(DATA_DIR / "sage_events.jsonl"))
)
AGENT_EVENTS_JSONL_PATH = Path(
    os.environ.get("SAGE_AGENT_EVENTS_JSONL", str(DATA_DIR / "agent_events.jsonl"))
)
UI_STATUS_PATH = Path(
    os.environ.get("SAGE_UI_STATUS_PATH", str(DATA_DIR / "ui_status.json"))
)
METRICS_EXPORTER_PORT = int(os.environ.get("SAGE_METRICS_PORT", "9108"))

# Keep for fallback compatibility; Prometheus is the primary source by default.
USE_KUBECTL_TOP = os.environ.get("SAGE_USE_KUBECTL_TOP", "0").lower() in ("1", "true", "yes")
