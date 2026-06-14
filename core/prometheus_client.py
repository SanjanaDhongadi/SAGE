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
