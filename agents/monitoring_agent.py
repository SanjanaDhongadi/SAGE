import time
import logging
import subprocess
import joblib
import numpy as np
from collections import defaultdict
from rich.console import Console
from rich.table import Table
from rich.live import Live
from datetime import datetime

from core.prometheus_client import get_pod_cpu, get_pod_memory, get_node_memory_percent
from core.feature_builder import PodFeatureBuilder
import agents.stress_injector as injector

clf = joblib.load("/home/SLA_Project/sage/models/clf_breach_probability.pkl")
reg = joblib.load("/home/SLA_Project/sage/models/reg_time_to_breach.pkl")

PODS = [f"web-app-{i}" for i in range(1, 13)] + [f"flask-app-{i}" for i in range(1, 13)]
WORKER_NODES = ["minikube-m02", "minikube-m03"]

WARN_THRESH = 0.05
CRIT_THRESH = 0.08
HEALTHY_THRESH = 0.02

console = Console()
pod_states = defaultdict(lambda: "HEALTHY")
pod_healthy_ticks = defaultdict(int)
pod_crit_ticks = defaultdict(int)
pod_feature_builders = {p: PodFeatureBuilder(p) for p in PODS}
pod_last_prob = defaultdict(float)
pod_last_ttb = defaultdict(lambda: 9999.0)
pod_cooldowns = defaultdict(float)
_remediation_callback = None

def set_remediation_callback(fn):
    global _remediation_callback
    _remediation_callback = fn

def _is_running(pod: str) -> bool:
    try:
        r = subprocess.run(["kubectl", "get", "pod", pod, "-o", "jsonpath={.status.phase}"],
                           capture_output=True, text=True, timeout=5)
        return r.stdout.strip() == "Running"
    except:
        return False

def _update_state(pod: str, prob: float, running: bool) -> str:
    if not running:
        pod_states[pod] = "CRASHED"
        return "CRASHED"
    if prob < HEALTHY_THRESH:
        pod_healthy_ticks[pod] += 1
        if pod_healthy_ticks[pod] >= 3 and pod_states[pod] in ("RECOVERING", "WARNING"):
            pod_states[pod] = "HEALTHY"
    else:
        pod_healthy_ticks[pod] = 0
    if prob > WARN_THRESH and pod_states[pod] == "HEALTHY":
        pod_states[pod] = "WARNING"
    elif prob > CRIT_THRESH:
        pod_crit_ticks[pod] += 1
        if pod_crit_ticks[pod] >= 2:
            pod_states[pod] = "CRITICAL"
    else:
        pod_crit_ticks[pod] = 0
    return pod_states[pod]

def _build_table() -> Table:
    t = Table(title="SAGE Live Dashboard", expand=True, show_lines=True)
    t.add_column("Pod", style="bold")
    t.add_column("State")
    t.add_column("Breach Prob")
    t.add_column("TTB (s)")
    t.add_column("CPU%")
    t.add_column("Mem%")
    t.add_column("Cooldown")
    colors = {"HEALTHY": "green", "WARNING": "yellow", "CRITICAL": "red", "CRASHED": "bold red", "RECOVERING": "cyan"}
    for pod in PODS:
        state = pod_states[pod]
        col = colors.get(state, "white")
        rem = max(0, int(pod_cooldowns[pod] - time.time()))
        feats = pod_feature_builders[pod].build_features()
        t.add_row(
            pod, f"[{col}]{state}[/{col}]",
            f"{pod_last_prob[pod]:.3f}",
            f"{pod_last_ttb[pod]:.0f}" if pod_last_ttb[pod] < 9000 else "—",
            f"{feats.get('cpu_util_percent', 0):.1f}",
            f"{feats.get('mem_util_percent', 0):.1f}",
            f"{rem}s" if rem > 0 else "—"
        )
    return t

def run_monitoring_loop():
    logging.info("[Monitor] Started")
    with Live(console=console, refresh_per_second=0.5) as live:
        while True:
            for node in WORKER_NODES:
                if get_node_memory_percent(node) > 85:
                    injector.pause()
                else:
                    injector.resume()

            for pod in PODS:
                try:
                    cpu = get_pod_cpu(pod)
                    mem = get_pod_memory(pod)
                    fb = pod_feature_builders[pod]
                    fb.update(cpu, mem)
                    fvec = np.array(fb.get_feature_vector()).reshape(1, -1)
                    prob = float(clf.predict(fvec)[0])
                    ttb = float(reg.predict(fvec)[0]) if prob > WARN_THRESH else 9999.0
                    pod_last_prob[pod] = prob
                    pod_last_ttb[pod] = ttb
                    state = _update_state(pod, prob, _is_running(pod))
                    
                    # Publish pod state update to the event bus
                    from core.event_bus import bus
                    rem = max(0, int(pod_cooldowns[pod] - time.time()))
                    bus.publish("pod_update", {
                        "pod": pod,
                        "state": state,
                        "breach_prob": prob,
                        "time_to_breach": ttb,
                        "cpu": cpu,
                        "mem": mem,
                        "cooldown": rem
                    })
                    
                    now = time.time()
                    if state in ("WARNING", "CRITICAL", "CRASHED") and now > pod_cooldowns[pod] and _remediation_callback:
                        pod_cooldowns[pod] = now + 300
                        pod_states[pod] = "RECOVERING"
                        
                        bus.publish("remediation_started", {
                            "pod": pod,
                            "state": state,
                            "breach_prob": prob,
                            "time_to_breach": ttb
                        })
                        
                        import threading
                        threading.Thread(
                            target=_remediation_callback,
                            args=({"pod": pod, "state": state, "features": fb.build_features(),
                                   "breach_prob": prob, "time_to_breach": ttb},),
                            daemon=True
                        ).start()
                except Exception as e:
                    logging.error(f"[Monitor] {pod}: {e}")

            live.update(_build_table())
            time.sleep(15)
