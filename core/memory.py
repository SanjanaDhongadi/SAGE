import json
import os
import numpy as np
from datetime import datetime
from sklearn.metrics.pairwise import cosine_similarity

MEMORY_PATH = "/home/SLA_Project/sage/data/episodic_memory.json"
SIMILARITY_THRESHOLD = 0.80

def _load() -> dict:
    if not os.path.exists(MEMORY_PATH):
        return {"incidents": []}
    with open(MEMORY_PATH, "r") as f:
        try:
            data = json.load(f)
        except Exception:
            return {"incidents": []}
        
        if "incidents" not in data and "episodes" in data:
            data["incidents"] = data["episodes"]
        elif "incidents" not in data:
            data["incidents"] = []
        return data

def _save(data: dict):
    with open(MEMORY_PATH, "w") as f:
        json.dump(data, f, indent=2)

def _to_vec(features: dict, keys: list) -> np.ndarray:
    return np.array([features.get(k, 0.0) for k in keys], dtype=float)

def find_similar(features: dict) -> dict | None:
    data = _load()
    if not data["incidents"]:
        return None
    
    best_score, best_ep = 0.0, None
    for ep in data["incidents"]:
        if "features_snapshot" not in ep:
            continue
        
        # Intersect keys to guarantee compatible dimensions
        common_keys = sorted(list(set(features.keys()) & set(ep["features_snapshot"].keys())))
        if not common_keys:
            continue
            
        q = _to_vec(features, common_keys).reshape(1, -1)
        ref = _to_vec(ep["features_snapshot"], common_keys).reshape(1, -1)
        
        try:
            score = float(cosine_similarity(q, ref)[0][0])
            if score > best_score:
                best_score, best_ep = score, ep
        except Exception:
            continue
            
    return best_ep if best_score >= SIMILARITY_THRESHOLD else None

def store_episode(episode: dict):
    data = _load()
    episode["id"] = f"ep_{len(data['incidents']) + 1:04d}"
    episode["timestamp"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    episode["priority"] = {"CRASHED": "high", "CRITICAL": "medium", "WARNING": "low"}.get(
        episode.get("trigger_state", "WARNING"), "low"
    )
    data["incidents"].append(episode)
    if len(data["incidents"]) > 500:
        data["incidents"] = sorted(
            data["incidents"],
            key=lambda e: ({"high": 0, "medium": 1, "low": 2}[e.get("priority", "low")], e.get("timestamp", ""))
        )[:500]
    _save(data)
