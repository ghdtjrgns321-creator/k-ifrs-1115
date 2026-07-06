"""/chat SSE 호출 — done 이벤트 1건 추출. 홀드아웃 러너 전용(외부 의존 없음)."""

from __future__ import annotations

import json
import time
from typing import Any

import httpx

BASE_URL = "http://localhost:8002"
TIMEOUT = 180


def call_chat(
    message: str, session_id: str | None = None
) -> tuple[dict[str, Any], float]:
    """POST /chat → (done_event, elapsed_sec). done 없으면 error dict."""
    start = time.time()
    done_event: dict[str, Any] | None = None
    error_msg: str | None = None

    payload: dict[str, Any] = {"message": message}
    if session_id:
        payload["session_id"] = session_id

    with httpx.Client(timeout=httpx.Timeout(TIMEOUT, connect=10)) as client:
        with client.stream(
            "POST",
            f"{BASE_URL}/chat",
            json=payload,
            headers={"Accept": "text/event-stream"},
        ) as resp:
            for line in resp.iter_lines():
                line = line.strip()
                if not line.startswith("data: "):
                    continue
                try:
                    event = json.loads(line[6:])
                except json.JSONDecodeError:
                    continue
                if event.get("type") == "done":
                    done_event = event
                elif event.get("type") == "error":
                    error_msg = event.get("message", "unknown error")

    elapsed = time.time() - start
    if done_event:
        return done_event, elapsed
    if error_msg:
        return {"type": "error", "message": error_msg}, elapsed
    return {"type": "error", "message": "no done event received"}, elapsed
