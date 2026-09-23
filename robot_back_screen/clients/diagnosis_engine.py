"""Adapters for the existing diagnosis rule engine protocol."""

from __future__ import annotations

import copy
import os
import uuid
from datetime import datetime, timezone
from typing import Any


def now_text() -> str:
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S")


class MockDiagnosisEngine:
    """Implements the documented rule protocol for local UI development only."""

    def __init__(self) -> None:
        self._events: dict[str, dict[str, Any]] = {}
        self._alarms: dict[str, dict[str, Any]] = {}
        self._fields = [
            {"field": "battery_level", "description": "电池电量", "type": "float", "view": "battery_info", "allowed_ops": ["less_than", "greater_than", "between"]},
            {"field": "battery_voltage", "description": "电池电压", "type": "float", "view": "battery_info", "allowed_ops": ["less_than", "greater_than", "between"]},
            {"field": "lidar_online", "description": "雷达在线状态", "type": "bool", "view": "lidar_info", "allowed_ops": ["boolean_true", "boolean_false", "equals", "not_equals"]},
            {"field": "camera_online", "description": "摄像头在线状态", "type": "bool", "view": "camera_info", "allowed_ops": ["boolean_true", "boolean_false", "equals", "not_equals"]},
        ]
        self.register(
            {
                "name": "电池低电量检测",
                "enabled": True,
                "rule": {"field": "battery_level", "op": "less_than", "value": 0.2, "for_seconds": 3},
                "alarm": {"major_code": "10", "minor_code": "001", "name": "电池电量低", "severity": 2, "description": "检测到电池电量低于阈值", "recovery": "请尽快充电或更换电池"},
            }
        )

    def register(self, event: dict[str, Any]) -> dict[str, Any]:
        event = copy.deepcopy(event)
        event_id = event.get("id") or str(uuid.uuid4())
        event["id"] = event_id
        event["enabled"] = bool(event.get("enabled", event.get("enable", True)))
        event.pop("enable", None)
        self._events[event_id] = event
        return {"success": True, "action": "register", "event_id": event_id, "event_name": event.get("name", ""), "message": "event applied"}

    def list_events(self) -> list[dict[str, Any]]:
        return [copy.deepcopy(event) for event in self._events.values()]

    def update(self, event_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        if event_id not in self._events:
            raise KeyError(event_id)
        event = self._events[event_id]
        for key, value in patch.items():
            if key in {"rule", "alarm"} and isinstance(value, dict):
                event.setdefault(key, {}).update(value)
            elif key != "id":
                event[key] = value
        if "enable" in event:
            event["enabled"] = bool(event.pop("enable"))
        return {"success": True, "action": "update", "event_id": event_id, "message": "event applied"}

    def unregister(self, event_id: str) -> dict[str, Any]:
        event = self._events.pop(event_id, None)
        if not event:
            raise KeyError(event_id)
        return {"success": True, "action": "unregister", "event_id": event_id, "message": "event removed"}

    def list_alarms(self) -> list[dict[str, Any]]:
        return [copy.deepcopy(alarm) for alarm in self._alarms.values()]

    def diagnose_all(self) -> dict[str, Any]:
        for event in self._events.values():
            if event.get("enabled"):
                alarm = event.get("alarm", {})
                key = f"{alarm.get('major_code', '99')}-{alarm.get('minor_code', '000')}"
                self._alarms[key] = {
                    **copy.deepcopy(alarm),
                    "event_id": event["id"],
                    "occurred_at": now_text(),
                    "occurrence_count": self._alarms.get(key, {}).get("occurrence_count", 0) + 1,
                }
        return {"success": True, "action": "diagnose_once", "message": "mock enabled rules evaluated"}

    def recover(self, major_code: str, minor_code: str) -> dict[str, Any]:
        self._alarms.pop(f"{major_code}-{minor_code}", None)
        return {"success": True, "action": "alarm_recover", "message": "alarm recovered"}

    def clear_alarms(self) -> int:
        """Clear local mock alarms so the back-screen demo has a complete loop.

        This is deliberately limited to the in-process mock engine.  A real
        diagnosis engine remains the source of truth and decides which
        recovered alarms may be cleared.
        """
        cleared_count = len(self._alarms)
        self._alarms.clear()
        return cleared_count

    def fields(self) -> list[dict[str, Any]]:
        return copy.deepcopy(self._fields)

    def state(self) -> int:
        return 1


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


def create_diagnosis_engine() -> MockDiagnosisEngine | WebSocketDiagnosisEngine:
    url = os.getenv("DIAGNOSIS_WS_URL", "").strip()
    return WebSocketDiagnosisEngine(url) if url else MockDiagnosisEngine()
