import subprocess
import logging
import time
import joblib
import numpy as np
from datetime import datetime
from langchain_groq import ChatGroq
from langgraph.graph import StateGraph, END
from typing import TypedDict, Optional
import openpyxl
import os

from core.memory import find_similar, store_episode
from core.feature_builder import PodFeatureBuilder
from core.prometheus_client import get_pod_cpu, get_pod_memory

REMED_LOG = "/home/SLA_Project/sage/data/remediation_log.xlsx"
clf = joblib.load("/home/SLA_Project/sage/models/clf_breach_probability.pkl")
llm = ChatGroq(model="llama-3.1-8b-instant", temperature=0, max_tokens=400)

class RemedState(TypedDict):
    pod: str
    state: str
    features: dict
    breach_prob: float
    time_to_breach: float
    memory_hit: Optional[dict]
    root_cause: str
    action: str
    reasoning: str
    outcome: str
    prob_after: float
    recovery_time: float

def _kubectl(cmd: list) -> str:
    try:
        r = subprocess.run(["kubectl"] + cmd, capture_output=True, text=True, timeout=15)
        return r.stdout.strip()
    except Exception as e:
        return str(e)

def _deployment(pod: str) -> str:
    parts = pod.split("-")
    return "-".join(parts[:3]) if pod.startswith("flask") else "-".join(parts[:2])

def _log(row: dict):
    if not os.path.exists(REMED_LOG):
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(["timestamp","pod","trigger_state","breach_prob_before","breach_prob_after",
                    "time_to_breach","root_cause","action_taken","reasoning","outcome",
                    "recovery_time_seconds","memory_used"])
        wb.save(REMED_LOG)
    wb = openpyxl.load_workbook(REMED_LOG)
    ws = wb.active
    ws.append([datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
               row.get("pod"), row.get("state"), row.get("breach_prob"),
               row.get("prob_after"), row.get("time_to_breach"),
               row.get("root_cause"), row.get("action"), row.get("reasoning"),
               row.get("outcome"), row.get("recovery_time"), row.get("memory_used")])
    wb.save(REMED_LOG)

def check_memory(state: RemedState) -> RemedState:
    state["memory_hit"] = find_similar(state["features"])
    return state

def llm_rca(state: RemedState) -> RemedState:
    if state["memory_hit"] and state["memory_hit"].get("outcome") == "SUCCESS":
        ep = state["memory_hit"]
        state["root_cause"] = ep["root_cause"]
        state["action"] = ep["action_taken"]
        state["reasoning"] = f"Memory match: reusing fix from {ep['timestamp']}"
    else:
        f = state["features"]
        prompt = f"""Pod: {state['pod']} | State: {state['state']} | Prob: {state['breach_prob']:.3f}
CPU: {f['cpu_util_percent']:.1f}% Mem: {f['mem_util_percent']:.1f}%
cpu_roc_15m: {f['cpu_roc_15m']:.3f} mem_roc_15m: {f['mem_roc_15m']:.3f}
cpu_dominant: {f['cpu_dominant']} mem_dominant: {f['mem_dominant']} both_high: {f['cpu_mem_both_high']}
TTB: {state['time_to_breach']:.0f}s

Diagnose and prescribe ONE action: scale_replicas, increase_cpu_limit, increase_memory_limit, increase_both_limits, wait_and_monitor.

ROOT_CAUSE: <one sentence>
ACTION: <action>
REASONING: <one sentence>"""

        resp = llm.invoke(prompt).content.strip()
        lines = {l.split(":")[0].strip(): ":".join(l.split(":")[1:]).strip() for l in resp.split("\n") if ":" in l}
        state["root_cause"] = lines.get("ROOT_CAUSE", "Unknown")
        state["action"] = lines.get("ACTION", "scale_replicas")
        state["reasoning"] = lines.get("REASONING", "LLM decision")

    from core.event_bus import bus
    bus.publish("rca_complete", {
        "pod": state["pod"],
        "root_cause": state["root_cause"],
        "action": state["action"],
        "reasoning": state["reasoning"]
    })
    return state

def execute_fix(state: RemedState) -> RemedState:
    action = state["action"].strip().lower()
    dep = _deployment(state["pod"])
    
    from core.event_bus import bus
    bus.publish("action_executed", {
        "pod": state["pod"],
        "action": state["action"]
    })
    
    if action == "scale_replicas":
        cur = int(_kubectl(["get", "deployment", dep, "-o", "jsonpath={.spec.replicas}"]) or 1)
        _kubectl(["scale", "deployment", dep, f"--replicas={cur + 1}"])
    elif action == "increase_cpu_limit":
        _kubectl(["set", "resources", "deployment", dep, "--limits=cpu=500m", "--requests=cpu=200m"])
    elif action == "increase_memory_limit":
        _kubectl(["set", "resources", "deployment", dep, "--limits=memory=512Mi", "--requests=memory=256Mi"])
    elif action == "increase_both_limits":
        _kubectl(["set", "resources", "deployment", dep, "--limits=cpu=500m,memory=512Mi", "--requests=cpu=200m,memory=256Mi"])
    else:
        logging.info(f"[Remediation] {state['pod']}: wait_and_monitor — no action taken")
    return state

def verify_outcome(state: RemedState) -> RemedState:
    start = time.time()
    time.sleep(180)
    try:
        fb = PodFeatureBuilder(state["pod"])
        cpu = get_pod_cpu(state["pod"])
        mem = get_pod_memory(state["pod"])
        fb.update(cpu, mem); fb.update(cpu, mem)
        fvec = np.array(fb.get_feature_vector()).reshape(1, -1)
        state["prob_after"] = float(clf.predict(fvec)[0])
    except:
        state["prob_after"] = state["breach_prob"]
    state["recovery_time"] = time.time() - start
    state["outcome"] = "SUCCESS" if state["prob_after"] < state["breach_prob"] * 0.6 else "PARTIAL"
    return state

def log_and_memorize(state: RemedState) -> RemedState:
    _log({**state, "memory_used": state["memory_hit"] is not None})
    store_episode({
        "pod": state["pod"],
        "deployment": _deployment(state["pod"]),
        "trigger_state": state["state"],
        "stress_type_detected": (
            "cpu_spike" if state["features"]["cpu_dominant"] else
            "memory_stress" if state["features"]["mem_dominant"] else "compound"
        ),
        "features_snapshot": {k: state["features"][k] for k in [
            "cpu_util_percent","mem_util_percent","cpu_roc_15m",
            "mem_roc_15m","cpu_mem_both_high","cpu_dominant","mem_dominant"
        ]},
        "root_cause": state["root_cause"],
        "llm_reasoning": state["reasoning"],
        "action_taken": state["action"],
        "breach_prob_before": state["breach_prob"],
        "breach_prob_after": state["prob_after"],
        "outcome": state["outcome"],
        "recovery_time_seconds": state["recovery_time"],
    })
    logging.info(f"[Remediation] {state['pod']}: {state['outcome']} | {state['breach_prob']:.3f}→{state['prob_after']:.3f}")
    
    from core.event_bus import bus
    bus.publish("remediation_complete", {
        "pod": state["pod"],
        "action": state["action"],
        "outcome": state["outcome"],
        "prob_before": state["breach_prob"],
        "prob_after": state["prob_after"],
        "recovery_time": state["recovery_time"]
    })
    return state

def build_remediation_graph():
    g = StateGraph(RemedState)
    g.add_node("check_memory", check_memory)
    g.add_node("llm_rca", llm_rca)
    g.add_node("execute_fix", execute_fix)
    g.add_node("verify", verify_outcome)
    g.add_node("log", log_and_memorize)
    g.set_entry_point("check_memory")
    g.add_edge("check_memory", "llm_rca")
    g.add_edge("llm_rca", "execute_fix")
    g.add_edge("execute_fix", "verify")
    g.add_edge("verify", "log")
    g.add_edge("log", END)
    return g.compile()

_graph = build_remediation_graph()

def handle_pod_event(payload: dict):
    _graph.invoke({
        "pod": payload["pod"], "state": payload["state"],
        "features": payload["features"], "breach_prob": payload["breach_prob"],
        "time_to_breach": payload["time_to_breach"],
        "memory_hit": None, "root_cause": "", "action": "",
        "reasoning": "", "outcome": "", "prob_after": 0.0, "recovery_time": 0.0,
    })
