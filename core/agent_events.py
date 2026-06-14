from __future__ import annotations

import json
import os
import time
from datetime import datetime
from typing import Any

from core.sage_config import AGENT_EVENTS_JSONL_PATH


def append_agent_event(
    component: str,
    level: str,
    message: str,
    **fields: Any,
) -> None:
    os.makedirs(os.path.dirname(str(AGENT_EVENTS_JSONL_PATH)), exist_ok=True)
    row = {
        "ts": time.time(),
        "iso": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "component": component,
        "level": level.upper(),
        "message": message,
    }
    if fields:
        row["fields"] = fields
    with open(str(AGENT_EVENTS_JSONL_PATH), "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
