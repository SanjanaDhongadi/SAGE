import os
import sys
import logging
import threading
from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, "/home/SLA_Project/sage")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", handlers=[logging.StreamHandler(sys.stdout)])

from agents.monitoring_agent import run_monitoring_loop, set_remediation_callback
from agents.stress_injector import run_injector_loop
from agents.remediation_agent import handle_pod_event
from core.dashboard_server import run_dashboard
from core.sage_metrics_exporter import run_exporter

def main():
    set_remediation_callback(handle_pod_event)
    
    # 1. Start SAGE Web Dashboard Server (port 5050)
    threading.Thread(target=run_dashboard, args=(5050,), daemon=True, name="Dashboard").start()
    
    # 2. Start SAGE Prometheus Exporter (port 9100)
    threading.Thread(target=run_exporter, args=(9100,), daemon=True, name="Exporter").start()
    
    # 3. Start Stress Injector and Monitoring loops
    threading.Thread(target=run_injector_loop, daemon=True, name="Injector").start()
    threading.Thread(target=run_monitoring_loop, daemon=True, name="Monitor").start()
    
    logging.info("==================================================================")
    logging.info("SAGE Orchestrator successfully initialized.")
    logging.info("→ Live Web Dashboard:  http://localhost:5050")
    logging.info("→ Prometheus Exporter: http://localhost:9100/metrics")
    logging.info("→ Chatbot:            python /home/SLA_Project/sage/chatbot.py")
    logging.info("==================================================================")
    
    threading.Event().wait()

if __name__ == "__main__":
    main()
