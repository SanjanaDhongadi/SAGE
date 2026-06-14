import logging
import threading
from prometheus_client import start_http_server, Gauge, Counter
from core.event_bus import bus

# Metrics Definitions
BREACH_PROB = Gauge('sage_breach_probability', 'Current SLA breach probability predicted by ML model', ['pod'])
TTB = Gauge('sage_time_to_breach_seconds', 'Predicted time to SLA breach in seconds', ['pod'])
POD_STATE = Gauge('sage_pod_state', 'Pod SAGE health state (0:HEALTHY, 1:WARNING, 2:CRITICAL, 3:CRASHED, 4:RECOVERING)', ['pod'])
REMEDIATIONS = Counter('sage_remediations_total', 'Total remediation actions triggered', ['pod', 'action', 'outcome'])
STRESS_INJECTED = Counter('sage_stress_injected_total', 'Total stress injection events', ['pod', 'stress_type'])

STATE_MAP = {
    "HEALTHY": 0.0,
    "WARNING": 1.0,
    "CRITICAL": 2.0,
    "CRASHED": 3.0,
    "RECOVERING": 4.0
}

def handle_event(event_type: str, data: dict):
    try:
        if event_type == "pod_update":
            pod = data.get("pod")
            prob = data.get("breach_prob", 0.0)
            ttb_val = data.get("time_to_breach", 9999.0)
            state = data.get("state", "HEALTHY")
            
            BREACH_PROB.labels(pod=pod).set(prob)
            TTB.labels(pod=pod).set(ttb_val)
            
            state_val = STATE_MAP.get(state.upper(), 0.0)
            POD_STATE.labels(pod=pod).set(state_val)
            
        elif event_type == "remediation_complete":
            # Event emitted when remediation finishes (success/failure)
            pod = data.get("pod")
            action = data.get("action", "unknown")
            outcome = data.get("outcome", "unknown")
            REMEDIATIONS.labels(pod=pod, action=action, outcome=outcome).inc()
            
        elif event_type == "stress_injected":
            pod = data.get("pod")
            stype = data.get("stress_type", "unknown")
            STRESS_INJECTED.labels(pod=pod, stress_type=stype).inc()
    except Exception as e:
        logging.error(f"[Exporter] Error handling event: {e}")

def run_exporter(port=9100):
    try:
        bus.subscribe("pod_update", handle_event)
        bus.subscribe("remediation_complete", handle_event)
        bus.subscribe("stress_injected", handle_event)
        
        start_http_server(port, addr='0.0.0.0')
        logging.info(f"[Exporter] SAGE Prometheus exporter listening on 0.0.0.0:{port} (/metrics)")
    except Exception as e:
        logging.error(f"[Exporter] Failed to start metrics exporter on port {port}: {e}")
