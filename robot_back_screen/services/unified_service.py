"""Combines telemetry with the existing diagnosis-engine protocol."""

from __future__ import annotations

import uuid
from typing import Any

from robot_back_screen.clients.diagnosis_engine import MockDiagnosisEngine, WebSocketDiagnosisEngine, now_text
from robot_back_screen.clients.remote_robot import RemoteRobotClient
from robot_back_screen.services.telemetry import MockTelemetryProvider, RosTelemetryProvider, create_telemetry_provider

SEVERITY_NAMES = {1: "info", 2: "warning", 3: "critical", 4: "emergency"}
SEVERITY_RANK = {"normal": 0, "info": 1, "warning": 2, "critical": 3, "emergency": 4}


class UnifiedDiagnosticsService:
    def __init__(self, engine: MockDiagnosisEngine | WebSocketDiagnosisEngine) -> None:
        self.engine = engine
        self.telemetry: MockTelemetryProvider | RosTelemetryProvider = create_telemetry_provider()
        # Pico 可选读取 Orin 的 HTTP 数据。未配置时仍是原来的单机模式。
        self.orin = RemoteRobotClient()
        self.history: list[dict[str, Any]] = []

    @staticmethod
    def _items(response: dict[str, Any] | None) -> list[dict[str, Any]]:
        if not response:
            return []
        data = response.get("data", response)
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
        return []

    @staticmethod
    def _merge_snapshot(local: dict[str, Any], orin: dict[str, Any] | None) -> dict[str, Any]:
        """Use Orin for whole-robot state and Pico for hands/wrist forces."""
        if not orin:
            return local
        merged = dict(orin)
        # Keep proven Pico-only measurements. They have no corresponding Orin
        # source and must never be replaced with empty remote fields.
        for key in ("hands", "wristForces"):
            if local.get(key):
                merged[key] = local[key]
        merged_sensors = dict(orin.get("sensors") or {})
        local_sensors = local.get("sensors") or {}
        if local_sensors.get("forceSensor") is not None:
            merged_sensors["forceSensor"] = local_sensors["forceSensor"]
        merged["sensors"] = merged_sensors
        merged_metrics = dict(orin.get("diagnosticMetrics") or {})
        merged_metrics.update(local.get("diagnosticMetrics") or {})
        if merged_metrics:
            merged["diagnosticMetrics"] = merged_metrics
        # 整机主网络地址来自 Orin；同时保留 Pico 的本机地址，供背屏顶部
        # 明确展示两台计算单元，而不是让用户误以为只有一台设备在线。
        merged_network = dict(orin.get("network") or {})
        pico_ip = (local.get("network") or {}).get("ip")
        if pico_ip:
            merged_network["picoIp"] = pico_ip
        merged["network"] = merged_network
        merged.setdefault("dataSources", {})["orin"] = "http"
        merged["dataSources"]["pico"] = "ros2"
        return merged

    async def _engine_action(self, action: str, **payload: Any) -> dict[str, Any]:
        if isinstance(self.engine, WebSocketDiagnosisEngine):
            return await self.engine.request(action, **payload)
        if action == "list_alarms":
            return {"success": True, "alarms": self.engine.list_alarms()}
        if action == "list_events":
            return {"success": True, "events": self.engine.list_events()}
        if action == "describe_data_view_fields":
            return {"success": True, "fields": self.engine.fields()}
        if action == "get_diagnosis_state":
            return {"success": True, "state": self.engine.state()}
        if action == "register":
            return self.engine.register(payload["event"])
        if action == "update":
            event = payload["event"]
            return self.engine.update(event["id"], event)
        if action == "unregister":
            return self.engine.unregister(payload["event"]["id"])
        if action == "diagnose_once":
            return self.engine.diagnose_all()
        if action == "alarm_recover":
            return self.engine.recover(payload["major_code"], payload["minor_code"])
        raise ValueError(f"Unsupported diagnosis action: {action}")

    @staticmethod
    def _severity(value: Any) -> str:
        if isinstance(value, int):
            return SEVERITY_NAMES.get(value, "warning")
        return str(value or "warning").lower()

    async def alarms(self) -> list[dict[str, Any]]:
        response = await self._engine_action("list_alarms", severity=0)
        raw_alarms = response.get("alarms", [])
        alarms = []
        for raw in raw_alarms:
            major = str(raw.get("major_code", "99"))
            minor = str(raw.get("minor_code", "000"))
            severity = self._severity(raw.get("severity"))
            code = f"{major}-{minor}"
            alarms.append({
                "id": code, "code": code, "severity": severity,
                "title": raw.get("alarm_name", raw.get("name", code)),
                "time": raw.get("occurred_at", now_text()),
                "desc": raw.get("description", ""), "suggestion": raw.get("recovery", "请检查机器人状态"),
                "occurrenceCount": raw.get("occurrence_count", 1),
                "label": "实时曲线 · 诊断数据", "values": [0, 0, 0, 0, 0],
            })
        local_alarms = alarms + await self.telemetry.diagnostic_alarms()
        orin_alarms = self._items(await self.orin.fetch("/alarms"))
        # IDs identify alarm lifecycle; deduplicate when both endpoints happen
        # to expose the same diagnostic item.
        combined = orin_alarms + local_alarms
        unique: dict[str, dict[str, Any]] = {}
        for alarm in combined:
            unique[str(alarm.get("id", uuid.uuid4()))] = alarm
        return list(unique.values())

    async def snapshot(self) -> dict[str, Any]:
        local_snapshot = await self.telemetry.snapshot()
        orin_snapshot = await self.orin.fetch("/robot/snapshot")
        snapshot = self._merge_snapshot(local_snapshot, orin_snapshot)
        alarms = await self.alarms()
        level = max((alarm["severity"] for alarm in alarms), key=lambda item: SEVERITY_RANK.get(item, 0), default="normal")
        label = {"normal": "系统健康", "info": "需注意", "warning": "系统警告", "critical": "系统异常", "emergency": "紧急停机"}.get(level, "系统健康")
        # ROS 适配器只收到关节流时，不能据此断言整机“健康”。只有诊断汇总
        # 也在线后，绿色才代表诊断系统给出的健康结论。
        telemetry_status = await self.telemetry_status()
        active_sources = telemetry_status.get("activeSources", [])
        has_diagnostics = any(str(source).endswith("diagnostics") for source in active_sources)
        if telemetry_status.get("telemetryMode") == "ros" and not has_diagnostics and not alarms:
            level = "info"
            label = "数据接入中" if active_sources else "等待 ROS 数据"
        snapshot["health"] = {"level": level, "label": label, "alertCount": len(alarms)}
        return snapshot

    async def work_summary(self) -> dict[str, Any]:
        return (await self.orin.fetch("/work-summary")) or await self.telemetry.work_summary()

    async def telemetry_status(self) -> dict[str, Any]:
        local = await self.telemetry.connection_status()
        # /healthz 位于 Orin 服务根路径，不在 /api/v1 下。
        orin = await self.orin.fetch_root("/healthz")
        if not orin:
            return local
        local_sources = [f"pico:{item}" for item in local.get("activeSources", [])]
        orin_sources = [f"orin:{item}" for item in orin.get("activeSources", [])]
        return {
            "telemetryMode": "ros",
            "dataSource": "robot",
            "dataReady": bool(local.get("dataReady") or orin.get("dataReady")),
            "activeSources": sorted(set(local_sources + orin_sources)),
            "orinConnected": True,
            "message": "已合并 Pico 手部数据与 Orin 整机数据",
        }

    async def diagnose(self) -> dict[str, Any]:
        # ROS 已接入但诊断引擎尚未接入时，绝不能退回到内存模拟引擎。
        # 否则用户点击背屏按钮会凭空出现一条“模拟告警”。
        if self.telemetry.mode == "ros" and isinstance(self.engine, MockDiagnosisEngine):
            message = "诊断引擎尚未接入：未执行诊断，也未生成告警"
            self._record("diagnose_unavailable", message)
            return {"accepted": False, "message": message}
        response = await self._engine_action("diagnose_once")
        self._record("diagnose", "已请求执行诊断规则")
        return {"accepted": bool(response.get("success", True)), "commandId": str(uuid.uuid4()), "engine": response}

    async def recover_alarm(self, alarm_id: str) -> dict[str, Any]:
        code = alarm_id.replace("_", "-")
        major, _, minor = code.partition("-")
        response = await self._engine_action("alarm_recover", major_code=major, minor_code=minor)
        self._record("alarm_recover", f"已请求恢复 {code}")
        return {"accepted": bool(response.get("success", True)), "commandId": str(uuid.uuid4()), "engine": response}

    async def clear_recovered(self) -> dict[str, Any]:
        # The mock engine has no separate "recovered" state.  Clear its
        # injected alarms so that the demonstration can return to healthy.
        # With a real engine, alarm lifecycle stays under that engine's
        # control; this endpoint is only a request to clear recovered alarms.
        if isinstance(self.engine, MockDiagnosisEngine) and self.telemetry.mode != "ros":
            cleared_count = self.engine.clear_alarms()
            message = f"已清除 {cleared_count} 条模拟告警"
        elif isinstance(self.engine, MockDiagnosisEngine):
            cleared_count = 0
            message = "诊断引擎尚未接入：未清除任何告警"
        else:
            cleared_count = 0
            message = "已请求清除已恢复告警"
        self._record("clear_recovered", message)
        return {
            "accepted": True,
            "commandId": str(uuid.uuid4()),
            "clearedCount": cleared_count,
            "message": message,
        }

    async def soft_stop(self) -> dict[str, Any]:
        await self.telemetry.soft_stop()
        self._record("soft_stop", "演示适配器已收到软件停止请求")
        return {"accepted": True, "commandId": str(uuid.uuid4()), "mock": isinstance(self.engine, MockDiagnosisEngine)}

    async def list_rules(self) -> list[dict[str, Any]]:
        return (await self._engine_action("list_events")).get("events", [])

    async def register_rule(self, event: dict[str, Any]) -> dict[str, Any]:
        response = await self._engine_action("register", event=event)
        self._record("rule_register", f"已注册规则 {event.get('name', '')}")
        return response

    async def update_rule(self, rule_id: str, event: dict[str, Any]) -> dict[str, Any]:
        response = await self._engine_action("update", event={**event, "id": rule_id})
        self._record("rule_update", f"已更新规则 {rule_id}")
        return response

    async def delete_rule(self, rule_id: str) -> dict[str, Any]:
        response = await self._engine_action("unregister", event={"id": rule_id})
        self._record("rule_unregister", f"已注销规则 {rule_id}")
        return response

    async def fields(self) -> list[dict[str, Any]]:
        return (await self._engine_action("describe_data_view_fields")).get("fields", [])

    async def diagnosis_state(self) -> dict[str, Any]:
        return await self._engine_action("get_diagnosis_state")

    async def logs(self) -> list[dict[str, Any]]:
        telemetry_logs = await self.telemetry.logs()
        orin_logs = self._items(await self.orin.fetch("/history"))
        service_logs = [
            {"time": item["time"].split(" ")[-1], "type": "info", "label": "背屏后端", "text": item["message"], "source": "背屏服务"}
            for item in self.history
        ]
        return (service_logs + orin_logs + telemetry_logs)[:200]

    def _record(self, kind: str, message: str) -> None:
        self.history.insert(0, {"time": now_text(), "kind": kind, "message": message})
        del self.history[200:]
