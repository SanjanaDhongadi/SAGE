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
