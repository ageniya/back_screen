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
        # 没有接入独立诊断引擎时，一键诊断仍可基于已收到的遥测数据
        # 进行只读检查。结果只保存在内存中，下一次检查会用新结果覆盖。
        self._builtin_alarms: list[dict[str, Any]] = []

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
        # 上肢关节和左右 TCP 目前由 Pico 提供。Orin 快照通常没有这些
        # 字段，因此合并时不能用 Orin 的空值覆盖 Pico 已收到的实时姿态。
        local_motion = local.get("motion") or {}
        merged_motion = dict(orin.get("motion") or {})
        if local_motion.get("jointPositions"):
            merged_motion["jointPositions"] = local_motion["jointPositions"]
        if any(item is not None for item in local_motion.get("joints", [])):
            merged_motion["joints"] = local_motion["joints"]
        for key in ("leftTcp", "rightTcp"):
            if local_motion.get(key):
                merged_motion[key] = local_motion[key]
        if merged_motion:
            merged["motion"] = merged_motion
        if local.get("upperLimbState"):
            merged["upperLimbState"] = local["upperLimbState"]
        merged_sensors = dict(orin.get("sensors") or {})
        local_sensors = local.get("sensors") or {}
        if local_sensors.get("forceSensor") is not None:
            merged_sensors["forceSensor"] = local_sensors["forceSensor"]
        merged["sensors"] = merged_sensors
        merged_metrics = dict(orin.get("diagnosticMetrics") or {})
        # Pico 的 diagnostics 通常只包含 CPU 平均值；不能用这个不完整
        # 字典整体覆盖 Orin resource 中已存在的内存、磁盘、GPU 和温度。
        for key, value in (local.get("diagnosticMetrics") or {}).items():
            remote_value = merged_metrics.get(key)
            if isinstance(remote_value, dict) and isinstance(value, dict):
                merged_metrics[key] = {**remote_value, **value}
            else:
                merged_metrics[key] = value
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
        local_alarms = alarms + self._builtin_alarms + await self.telemetry.diagnostic_alarms()
        orin_alarms = self._items(await self.orin.fetch("/alarms"))
        # IDs identify alarm lifecycle; deduplicate when both endpoints happen
        # to expose the same diagnostic item.
        combined = orin_alarms + local_alarms
        unique: dict[str, dict[str, Any]] = {}
        for alarm in combined:
            unique[str(alarm.get("id", uuid.uuid4()))] = alarm
        return list(unique.values())

    async def _current_snapshot(self) -> dict[str, Any]:
        """Collect the same combined Pico/Orin state used by the status page."""
        local_snapshot = await self.telemetry.snapshot()
        orin_snapshot = await self.orin.fetch("/robot/snapshot")
        return self._merge_snapshot(local_snapshot, orin_snapshot)

    async def snapshot(self) -> dict[str, Any]:
        snapshot = await self._current_snapshot()
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

    @staticmethod
    def _as_number(value: Any) -> float | None:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        return number if number == number else None  # filter NaN

    @staticmethod
    def _builtin_alarm(
        alarm_id: str, title: str, desc: str, suggestion: str, severity: str = "warning"
    ) -> dict[str, Any]:
        return {
            "id": alarm_id,
            "code": alarm_id.upper().replace("builtin-", "BUILTIN-"),
            "severity": severity,
            "title": title,
            "time": now_text(),
            "desc": desc,
            "suggestion": suggestion,
            "occurrenceCount": 1,
            "label": "一键诊断（实时数据）",
            "values": [],
        }

    async def _run_builtin_diagnosis(self) -> list[dict[str, Any]]:
        """Check only values actually present in the current ROS snapshot.

        Missing or stale fields are *unknown*, not faults.  This is important
        during gradual middleware rollout: lack of a publisher must not turn
        into a fabricated robot alarm.
        """
        snapshot = await self._current_snapshot()
        metrics = snapshot.get("diagnosticMetrics") or {}
        sensors = snapshot.get("sensors") or {}
        alarms: list[dict[str, Any]] = []

        def check_resource(prefix: str, label: str, resource: Any) -> None:
            if not isinstance(resource, dict):
                return
            limits = (
                ("cpuUsage", 90.0, "CPU 占用过高", "%", "请检查高负载进程。"),
                ("memoryUsage", 90.0, "内存占用过高", "%", "请检查内存占用与长期运行进程。"),
                ("diskUsage", 90.0, "磁盘占用过高", "%", "请清理日志或扩容存储空间。"),
                ("gpuUsage", 95.0, "GPU 占用过高", "%", "请检查视觉、推理等 GPU 任务。"),
                ("temperature", 80.0, "温度过高", "°C", "请检查散热、风扇和环境温度。"),
            )
            for field, threshold, title, unit, suggestion in limits:
                value = self._as_number(resource.get(field))
                if value is None or value < threshold:
                    continue
                severity = "critical" if field == "temperature" and value >= 90 else "warning"
                alarms.append(self._builtin_alarm(
                    f"builtin-{prefix}-{field}",
                    f"{label}{title}",
                    f"当前值 {value:.1f}{unit}，阈值 {threshold:.0f}{unit}。",
                    suggestion,
                    severity,
                ))

        check_resource("orin", "Orin ", metrics.get("systemResource"))
        check_resource("pico", "Pico ", metrics.get("picoResource"))

        sensor_names = {
            "lidar": "激光雷达", "depthCamera": "深度相机", "forceSensor": "六维力传感器",
            "bumper": "碰撞条", "camera": "摄像头", "network": "网络",
        }
        for key, label in sensor_names.items():
            # False means this source has been seen previously but is now
            # offline; None means it has not been wired into middleware yet.
            if sensors.get(key) is False:
                alarms.append(self._builtin_alarm(
                    f"builtin-sensor-{key}",
                    f"{label}离线",
                    f"后端最近未收到{label}的有效数据。",
                    "请检查设备供电、线缆、驱动节点和 ROS2 话题。",
                    "critical" if key == "network" else "warning",
                ))

        self._builtin_alarms = alarms
        return alarms

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
        # 独立诊断引擎尚未接入时，不使用 MockDiagnosisEngine 生成虚假
        # 告警，而是直接检查此刻已经读取到的 ROS 遥测数据。
        if self.telemetry.mode == "ros" and isinstance(self.engine, MockDiagnosisEngine):
            alarms = await self._run_builtin_diagnosis()
            # `diagnostic_alarms()` and Orin also contain direct diagnostic
            # flags (for example resource over-CPU).  Return the complete
            # current result so the button feedback agrees with the alarm tab.
            total_count = len(await self.alarms())
            message = f"已检查当前可读取数据，当前共有 {total_count} 条问题"
            self._record("builtin_diagnose", message)
            return {
                "accepted": True,
                "commandId": str(uuid.uuid4()),
                "mode": "builtin_telemetry",
                "alarmCount": total_count,
                "message": message,
            }
        response = await self._engine_action("diagnose_once")
        self._record("diagnose", "已请求执行诊断规则")
        return {"accepted": bool(response.get("success", True)), "commandId": str(uuid.uuid4()), "engine": response}

    async def recover_alarm(self, alarm_id: str) -> dict[str, Any]:
        if self.telemetry.mode == "ros" and isinstance(self.engine, MockDiagnosisEngine) and alarm_id.startswith("builtin-"):
            remaining = await self._run_builtin_diagnosis()
            still_active = any(item["id"] == alarm_id for item in remaining)
            message = "问题仍存在，请先在实机处理后再确认" if still_active else "已重新检查，该问题已恢复"
            self._record("builtin_alarm_recheck", message)
            return {"accepted": not still_active, "commandId": str(uuid.uuid4()), "message": message}
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
            before = len(self._builtin_alarms)
            remaining = await self._run_builtin_diagnosis()
            cleared_count = max(0, before - len(remaining))
            message = f"已重新检查，清除 {cleared_count} 条已恢复问题；仍有 {len(remaining)} 条问题"
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
