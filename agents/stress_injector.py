import subprocess
import time
import random
import logging
import threading
from datetime import datetime
from langchain_groq import ChatGroq
from langgraph.graph import StateGraph, END
from typing import TypedDict
import openpyxl
import os

STRESS_LOG = "/home/SLA_Project/sage/data/stress_log.xlsx"
_pause_flag = threading.Event()
_pause_flag.set()

llm = ChatGroq(model="llama-3.1-8b-instant", temperature=0, max_tokens=200)

PODS = [f"web-app-{i}" for i in range(1, 13)] + [f"flask-app-{i}" for i in range(1, 13)]

class InjectorState(TypedDict):
    pod_metrics: dict
    selected_pod: str
    stress_type: str
    duration: int
    reasoning: str

def _kubectl_exec(pod: str, cmd: str):
    try:
        subprocess.Popen(
            ["kubectl", "exec", pod, "--", "sh", "-c", cmd],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
    except Exception as e:
        logging.warning(f"kubectl exec failed {pod}: {e}")

def _get_metrics() -> dict:
    from core.prometheus_client import get_pod_cpu, get_pod_memory
    return {p: {"cpu": get_pod_cpu(p), "mem": get_pod_memory(p)} for p in PODS}

def _log_stress(pod, stype, duration, reasoning):
    if not os.path.exists(STRESS_LOG):
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(["timestamp", "pod", "stress_type", "duration_seconds", "reasoning"])
        wb.save(STRESS_LOG)
    wb = openpyxl.load_workbook(STRESS_LOG)
    ws = wb.active
    ws.append([datetime.now().strftime("%Y-%m-%d %H:%M:%S"), pod, stype, duration, reasoning])
    wb.save(STRESS_LOG)

def observe_node(state: InjectorState) -> InjectorState:
    state["pod_metrics"] = _get_metrics()
    return state

def decide_stress(state: InjectorState) -> InjectorState:
    summary = "\n".join(f"{p}: cpu={v['cpu']:.1f}% mem={v['mem']:.1f}%" for p, v in state["pod_metrics"].items())
    prompt = f"""Pod metrics:
{summary}

Pick the healthiest pod (lowest cpu+mem). Decide stress type: cpu_spike, cpu_gradual, memory_stress, or compound.
Rule: cpu>70→memory_stress; mem>70→cpu_spike; both<40→compound. Duration 120-300s.

Reply EXACTLY:
POD: <name>
TYPE: <type>
DURATION: <seconds>
REASON: <one sentence>"""

    resp = llm.invoke(prompt).content.strip()
    lines = {l.split(":")[0].strip(): ":".join(l.split(":")[1:]).strip() for l in resp.split("\n") if ":" in l}
    state["selected_pod"] = lines.get("POD", PODS[0])
    state["stress_type"] = lines.get("TYPE", "cpu_spike")
    state["duration"] = int(lines.get("DURATION", "180") or 180)
    state["reasoning"] = lines.get("REASON", "LLM decision")
    return state

def inject_stress(state: InjectorState) -> InjectorState:
    pod, stype, dur = state["selected_pod"], state["stress_type"], state["duration"]
    cmds = {
        "cpu_spike": f"dd if=/dev/zero of=/dev/null & dd if=/dev/zero of=/dev/null & dd if=/dev/zero of=/dev/null & sleep {dur} && kill %1 %2 %3 2>/dev/null",
        "cpu_gradual": f"dd if=/dev/zero of=/dev/null & sleep {dur} && kill %1 2>/dev/null",
        "memory_stress": f"dd if=/dev/zero of=/tmp/ms bs=1M count=200 & sleep {dur} && rm -f /tmp/ms && kill %1 2>/dev/null",
        "compound": f"dd if=/dev/zero of=/dev/null & dd if=/dev/zero of=/tmp/ms bs=1M count=150 & sleep {dur} && kill %1 %2 2>/dev/null && rm -f /tmp/ms",
    }
    _kubectl_exec(pod, cmds.get(stype, cmds["cpu_spike"]))
    _log_stress(pod, stype, dur, state["reasoning"])
    
    from core.event_bus import bus
    bus.publish("stress_injected", {
        "pod": pod,
        "stress_type": stype,
        "duration": dur,
        "reasoning": state["reasoning"]
    })
    
    logging.info(f"[Injector] {stype} → {pod} for {dur}s")
    return state

def build_injector_graph():
    g = StateGraph(InjectorState)
    g.add_node("observe", observe_node)
    g.add_node("decide", decide_stress)
    g.add_node("inject", inject_stress)
    g.set_entry_point("observe")
    g.add_edge("observe", "decide")
    g.add_edge("decide", "inject")
    g.add_edge("inject", END)
    return g.compile()

def pause(): _pause_flag.clear()
def resume(): _pause_flag.set()

def run_injector_loop():
    graph = build_injector_graph()
    logging.info("[Injector] Started")
    while True:
        _pause_flag.wait()
        try:
            graph.invoke({"pod_metrics": {}, "selected_pod": "", "stress_type": "", "duration": 180, "reasoning": ""})
        except Exception as e:
            logging.error(f"[Injector] {e}")
        time.sleep(random.randint(120, 300))
