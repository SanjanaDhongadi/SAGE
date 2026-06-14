import logging
import time
import os
from flask import Flask, render_template, jsonify
from flask_socketio import SocketIO
from core.event_bus import bus

# Disable flask console logging to avoid cluttering orchestrator stdout
log = logging.getLogger('wsgi')
log.setLevel(logging.ERROR)
cli = logging.getLogger('werkzeug')
cli.setLevel(logging.ERROR)

app = Flask(__name__, 
            template_folder="/home/SLA_Project/sage/templates", 
            static_folder="/home/SLA_Project/sage/static")
app.config['SECRET_KEY'] = 'sage-secret!'
socketio = SocketIO(app, cors_allowed_origins="*")

# In-memory store for dashboard state
PODS_STATE = {}
RECENT_EVENTS = []
MAX_EVENT_HISTORY = 100

def add_to_history(event_type, data):
    event = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "type": event_type,
        "data": data
    }
    RECENT_EVENTS.append(event)
    if len(RECENT_EVENTS) > MAX_EVENT_HISTORY:
        RECENT_EVENTS.pop(0)
    return event

def handle_bus_event(event_type: str, data: dict):
    try:
        # Cache active pod states
        if event_type == "pod_update":
            pod = data.get("pod")
            if pod:
                PODS_STATE[pod] = {
                    "pod": pod,
                    "state": data.get("state"),
                    "breach_prob": data.get("breach_prob"),
                    "time_to_breach": data.get("time_to_breach"),
                    "cpu": data.get("cpu"),
                    "mem": data.get("mem"),
                    "cooldown": data.get("cooldown"),
                    "last_update": time.time()
                }
            # Emit directly to WebSocket clients
            socketio.emit("pod_update", data)
            
        else:
            # For remediation, stress, etc., record in history and broadcast
            evt = add_to_history(event_type, data)
            socketio.emit("system_event", evt)
            
    except Exception as e:
        logging.error(f"[DashboardServer] Error handling bus event: {e}")

# Subscribe dashboard server to the event bus
bus.subscribe("*", handle_bus_event)

@app.route("/")
def index():
    return render_template("dashboard.html")

@app.route("/api/state")
def get_state():
    return jsonify({
        "pods": list(PODS_STATE.values()),
        "history": RECENT_EVENTS
    })

@socketio.on('connect')
def handle_connect():
    # Send initial state to newly connected client
    socketio.emit("init_state", {
        "pods": list(PODS_STATE.values()),
        "history": RECENT_EVENTS
    })

def run_dashboard(port=5050):
    try:
        logging.info(f"[Dashboard] Starting SAGE Web Dashboard on http://0.0.0.0:{port}")
        socketio.run(app, host='0.0.0.0', port=port, allow_unsafe_werkzeug=True)
    except Exception as e:
        logging.error(f"[Dashboard] Server error: {e}")
