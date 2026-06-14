#!/bin/bash
set -e

SAGE="/home/SLA_Project/sage"

# ---- core/prometheus_client.py ----
cat > "$SAGE/core/prometheus_client.py" << 'EOF'
import requests
import logging

PROMETHEUS_URL = "http://localhost:9090"

def query(promql: str) -> list:
    try:
        r = requests.get(f"{PROMETHEUS_URL}/api/v1/query", params={"query": promql}, timeout=5)
        r.raise_for_status()
        return r.json().get("data", {}).get("result", [])
    except Exception as e:
        logging.warning(f"Prometheus query failed: {e}")
        return []

def get_pod_cpu(pod_name: str) -> float:
    results = query(f'rate(container_cpu_usage_seconds_total{{pod=~"{pod_name}.*",container!=""}}[2m])')
    if results:
        return float(results[0]["value"][1]) * 100
    return 0.0

def get_pod_memory(pod_name: str) -> float:
    usage = query(f'container_memory_usage_bytes{{pod=~"{pod_name}.*",container!=""}}')
    limit = query(f'container_spec_memory_limit_bytes{{pod=~"{pod_name}.*",container!=""}}')
    if usage and limit:
        u = float(usage[0]["value"][1])
        l = float(limit[0]["value"][1])
        if l > 0:
            return (u / l) * 100
    return 0.0

def get_node_memory_percent(node: str) -> float:
    results = query(f'(1 - node_memory_MemAvailable_bytes{{node="{node}"}} / node_memory_MemTotal_bytes{{node="{node}"}}) * 100')
    if results:
        return float(results[0]["value"][1])
    return 0.0

def get_running_pods(node: str) -> list:
    results = query(f'kube_pod_info{{node="{node}"}}')
    return [r["metric"].get("pod", "") for r in results if r["metric"].get("pod")]
EOF

# ---- core/feature_builder.py ----
cat > "$SAGE/core/feature_builder.py" << 'EOF'
import numpy as np
from collections import deque
from typing import Dict

HISTORY_LEN = 20

class PodFeatureBuilder:
    def __init__(self, pod_name: str):
        self.pod = pod_name
        self.cpu_history = deque(maxlen=HISTORY_LEN)
        self.mem_history = deque(maxlen=HISTORY_LEN)

    def update(self, cpu: float, mem: float):
        self.cpu_history.append(cpu)
        self.mem_history.append(mem)

    def build_features(self) -> Dict:
        cpu = list(self.cpu_history) or [0.0, 0.0]
        mem = list(self.mem_history) or [0.0, 0.0]
        if len(cpu) < 2: cpu = cpu + [0.0] * (2 - len(cpu))
        if len(mem) < 2: mem = mem + [0.0] * (2 - len(mem))

        def safe_roc(arr):
            return (arr[-1] - arr[0]) / max(len(arr), 1) if len(arr) >= 2 else 0.0

        def wmean(arr, n):
            return float(np.mean(arr[-n:])) if len(arr) >= n else float(np.mean(arr))

        def wstd(arr, n):
            return float(np.std(arr[-n:])) if len(arr) >= n else float(np.std(arr))

        cpu_now, mem_now = cpu[-1], mem[-1]

        return {
            "cpu_util_percent": cpu_now,
            "mem_util_percent": mem_now,
            "cpu_mean_1m": wmean(cpu, 4),
            "cpu_mean_5m": wmean(cpu, 20),
            "cpu_mean_15m": wmean(cpu, 20),
            "mem_mean_1m": wmean(mem, 4),
            "mem_mean_5m": wmean(mem, 20),
            "mem_mean_15m": wmean(mem, 20),
            "cpu_roc_1m": safe_roc(cpu[-4:]),
            "cpu_roc_5m": safe_roc(cpu[-20:]),
            "cpu_roc_15m": safe_roc(cpu),
            "mem_roc_1m": safe_roc(mem[-4:]),
            "mem_roc_5m": safe_roc(mem[-20:]),
            "mem_roc_15m": safe_roc(mem),
            "cpu_std_1m": wstd(cpu, 4),
            "cpu_std_5m": wstd(cpu, 20),
            "mem_std_1m": wstd(mem, 4),
            "mem_std_5m": wstd(mem, 20),
            "cpu_lag_1": cpu[-2] if len(cpu) >= 2 else cpu[-1],
            "cpu_lag_2": cpu[-3] if len(cpu) >= 3 else cpu[-1],
            "mem_lag_1": mem[-2] if len(mem) >= 2 else mem[-1],
            "mem_lag_2": mem[-3] if len(mem) >= 3 else mem[-1],
            "cpu_baseline_dev": cpu_now - wmean(cpu, 20),
            "mem_baseline_dev": mem_now - wmean(mem, 20),
            "cpu_mem_product": cpu_now * mem_now / 10000,
            "cpu_mem_both_high": 1.0 if cpu_now > 70 and mem_now > 70 else 0.0,
            "cpu_dominant": 1.0 if cpu_now > mem_now + 30 else 0.0,
            "mem_dominant": 1.0 if mem_now > cpu_now + 30 else 0.0,
        }

    def get_feature_vector(self) -> list:
        f = self.build_features()
        ordered_keys = [
            "cpu_util_percent", "mem_util_percent",
            "cpu_mean_1m", "cpu_mean_5m", "cpu_mean_15m",
            "mem_mean_1m", "mem_mean_5m", "mem_mean_15m",
            "cpu_roc_1m", "cpu_roc_5m", "cpu_roc_15m",
            "mem_roc_1m", "mem_roc_5m", "mem_roc_15m",
            "cpu_std_1m", "cpu_std_5m",
            "mem_std_1m", "mem_std_5m",
            "cpu_lag_1", "cpu_lag_2",
            "mem_lag_1", "mem_lag_2",
            "cpu_baseline_dev", "mem_baseline_dev",
            "cpu_mem_product", "cpu_mem_both_high",
            "cpu_dominant", "mem_dominant",
        ]
        return [f.get(k, 0.0) for k in ordered_keys]
EOF

# ---- core/memory.py ----
cat > "$SAGE/core/memory.py" << 'EOF'
import json
import os
import numpy as np
from datetime import datetime
from sklearn.metrics.pairwise import cosine_similarity

MEMORY_PATH = "/home/SLA_Project/sage/data/episodic_memory.json"
SIMILARITY_THRESHOLD = 0.80

def _load() -> dict:
    if not os.path.exists(MEMORY_PATH):
        return {"episodes": []}
    with open(MEMORY_PATH, "r") as f:
        return json.load(f)

def _save(data: dict):
    with open(MEMORY_PATH, "w") as f:
        json.dump(data, f, indent=2)

def _to_vec(features: dict) -> np.ndarray:
    keys = sorted(features.keys())
    return np.array([features.get(k, 0.0) for k in keys], dtype=float)

def find_similar(features: dict) -> dict | None:
    data = _load()
    if not data["episodes"]:
        return None
    q = _to_vec(features).reshape(1, -1)
    best_score, best_ep = 0.0, None
    for ep in data["episodes"]:
        score = float(cosine_similarity(q, _to_vec(ep["features_snapshot"]).reshape(1, -1))[0][0])
        if score > best_score:
            best_score, best_ep = score, ep
    return best_ep if best_score >= SIMILARITY_THRESHOLD else None

def store_episode(episode: dict):
    data = _load()
    episode["id"] = f"ep_{len(data['episodes']) + 1:04d}"
    episode["timestamp"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    episode["priority"] = {"CRASHED": "high", "CRITICAL": "medium", "WARNING": "low"}.get(
        episode.get("trigger_state", "WARNING"), "low"
    )
    data["episodes"].append(episode)
    if len(data["episodes"]) > 500:
        data["episodes"] = sorted(
            data["episodes"],
            key=lambda e: ({"high": 0, "medium": 1, "low": 2}[e["priority"]], e["timestamp"])
        )[:500]
    _save(data)
EOF

echo "Core modules written successfully"
