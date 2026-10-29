"""Adapters for the existing diagnosis rule engine protocol."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any


def now_text() -> str:
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S")


class WebSocketDiagnosisEngine:
    """Thin client for the documented :8058 engine; URL/auth are deployment config."""

    def __init__(self, url: str) -> None:
        self.url = url

    async def request(self, action: str, **payload: Any) -> dict[str, Any]:
        import json
        import websockets

        message = {"action": action, **payload}
        async with websockets.connect(self.url, open_timeout=5, close_timeout=3) as socket:
            await socket.send(json.dumps(message, ensure_ascii=False))
            return json.loads(await socket.recv())


def create_diagnosis_engine() -> WebSocketDiagnosisEngine | None:
    url = os.getenv("DIAGNOSIS_WS_URL", "").strip()
    return WebSocketDiagnosisEngine(url) if url else None
