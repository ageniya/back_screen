import threading
import asyncio
import time
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from robot_back_screen.services.telemetry import RosTelemetryProvider
from robot_back_screen.services.unified_service import UnifiedDiagnosticsService
from robot_back_screen.services.chassis_reset import ChassisResetState


class MainControlBoundaryTests(unittest.IsolatedAsyncioTestCase):
    def reset_provider(self):
        provider = object.__new__(RosTelemetryProvider)
        provider._control_enabled = True
        provider._reset_control_enabled = True
        provider._lock = threading.Lock()
        provider._reset_request_lock = asyncio.Lock()
        provider._reset_machine = ChassisResetState()
        provider._reset_machine.update_chassis(False, False, 4, '等待复位')
        provider._reset_machine.update_velocity((0, 0, 0), (0, 0, 0))
        provider._sensor_timeout = 3
        provider._reset_supervisor_status = provider._reset_machine.view(True, True, True)
        provider._reset_supervisor_status['owner'] = 'back_screen_motion_supervisor'
        provider._reset_supervisor_at = time.monotonic()
        provider._reset_service = '/zj_humanoid/back_screen/reset'
        provider._reset_client = SimpleNamespace(service_is_ready=lambda: True)
        return provider

    async def test_failed_supervisor_request_never_falls_back_to_chassis_reset(self):
        provider = self.reset_provider()
        provider._call_trigger = AsyncMock(side_effect=RuntimeError('队列未清空'))
        with self.assertRaises(RuntimeError):
            await provider.reset_chassis()
        self.assertEqual(provider._call_trigger.await_count, 1)
        self.assertEqual(provider._call_trigger.await_args.args[1], provider._reset_service)

    async def test_local_emergency_overrides_remote_ready_status(self):
        provider = self.reset_provider()
        provider._reset_machine.update_chassis(True, False, 4, '等待复位 (急停中)')
        provider._call_trigger = AsyncMock()
        result = await provider.reset_chassis()
        self.assertFalse(result['sent'])
        provider._call_trigger.assert_not_awaited()

    async def test_reset_acceptance_waits_for_feedback_not_service_success(self):
        provider = self.reset_provider()
        provider._call_trigger = AsyncMock()
        result = await provider.reset_chassis()
        self.assertTrue(result['sent'])
        self.assertEqual([x.args[1] for x in provider._call_trigger.await_args_list],
                         [provider._reset_service])
        self.assertNotEqual(provider._reset_machine.state, 'RESET_DONE')

    async def test_active_ros_alarm_cannot_be_acknowledged_as_recovered(self):
        service = object.__new__(UnifiedDiagnosticsService)
        service.engine = None
        service._record = Mock()
        service.alarms = AsyncMock(return_value=[{'id': 'ros-0-/Battery'}])
        result = await service.recover_alarm('ros-0-/Battery')
        self.assertFalse(result['accepted'])
        service.alarms.return_value = []
        result = await service.recover_alarm('ros-0-/Battery')
        self.assertTrue(result['accepted'])

    def test_stale_diagnostics_are_distinct_from_hardware_errors(self):
        provider = object.__new__(RosTelemetryProvider)
        provider._lock = threading.Lock()
        provider._mark_data_received_locked = Mock()
        provider._on_diagnostics(SimpleNamespace(status=[
            SimpleNamespace(level=b'\x03', name='/Battery', message='Stale', values=[]),
            SimpleNamespace(level=2, name='Motor', message='Driver failure', values=[]),
        ]))
        stale, failure = provider._diagnostic_alarms
        self.assertEqual(stale['severity'], 'warning')
        self.assertEqual(stale['title'], '电池诊断数据过期')
        self.assertEqual(stale['code'], 'ROS-3')
        self.assertEqual(failure['severity'], 'critical')
        self.assertEqual(failure['desc'], 'Driver failure')
        provider._on_diagnostics(SimpleNamespace(status=[]), '/other/diagnostics_agg')
        self.assertEqual(len(provider._diagnostic_alarms), 2)
        provider._on_diagnostics(SimpleNamespace(status=[]), '/diagnostics_agg')
        self.assertEqual(provider._diagnostic_alarms, [])

    async def test_real_reset_never_bypasses_unconnected_main_controller(self):
        provider = self.reset_provider()
        provider._reset_supervisor_at = None
        provider._call_trigger = AsyncMock()
        result = await provider.reset_chassis()
        self.assertFalse(result["sent"])
        self.assertIn("复位主控未上线", result["message"])
        provider._call_trigger.assert_not_awaited()

    async def test_unified_api_rejects_unconnected_reset_without_success_log(self):
        service = object.__new__(UnifiedDiagnosticsService)
        service.telemetry = SimpleNamespace(reset_chassis=AsyncMock(return_value={"sent": False, "message": "主控复位接口尚未接入"}))
        service._record = Mock()
        result = await service.reset_chassis()
        self.assertFalse(result["accepted"])
        service._record.assert_not_called()

    async def test_active_estop_overrides_health_even_without_diagnostics(self):
        service = object.__new__(UnifiedDiagnosticsService)
        service._current_snapshot = AsyncMock(return_value={
            "diagnosticMetrics": {"chassisState": {"emergency": True}},
        })
        service.alarms = AsyncMock(return_value=[])
        service.telemetry_status = AsyncMock(return_value={"telemetryMode": "ros", "activeSources": []})
        service._visible_resource_alerts = {}
        snapshot = await service.snapshot()
        self.assertEqual(snapshot["health"]["level"], "emergency")

    async def test_generic_ros_levels_are_hidden_for_both_hosts_and_removed_from_counts(self):
        service = object.__new__(UnifiedDiagnosticsService)
        service.engine = None
        service._run_builtin_diagnosis = AsyncMock()
        service._engine_action = AsyncMock(return_value={})
        local_ros = [
            {"id": f"local-{level}", "code": f"ROS-{level}", "severity": "critical"}
            for level in (1, 2, 3)
        ]
        remote_ros = [
            {"id": f"remote-{level}", "code": f"ROS-{level}", "severity": "critical"}
            for level in (1, 2, 3)
        ]
        resource = {"id": "builtin-pico-memoryUsage", "code": "BUILTIN-PICO-MEMORYUSAGE", "severity": "warning"}
        specific = {"id": "motor-fault", "code": "MOTOR-42", "severity": "warning"}
        service._builtin_alarms = [resource]
        service.telemetry = SimpleNamespace(diagnostic_alarms=AsyncMock(return_value=local_ros))
        service.orin = SimpleNamespace(fetch=AsyncMock(return_value={"data": remote_ros + [specific]}))
        service._diagnosis_metrics = {}
        hidden_ids = {alarm["id"] for alarm in local_ros + remote_ros}
        service._visible_alarm_ids = set(hidden_ids)
        service._pending_alarm_since = {alarm_id: 0 for alarm_id in hidden_ids}
        service._alarm_persist_seconds = 0
        service._current_snapshot = AsyncMock(return_value={})
        service.telemetry_status = AsyncMock(return_value={"telemetryMode": "ros", "activeSources": ["pico:diagnostics"]})

        alarms = await service.alarms()
        self.assertEqual({alarm["id"] for alarm in alarms}, {resource["id"], specific["id"]})
        self.assertFalse(hidden_ids & service._visible_alarm_ids)
        self.assertFalse(hidden_ids & service._pending_alarm_since.keys())
        snapshot = await service.snapshot()
        self.assertEqual(snapshot["health"]["alertCount"], 2)
        self.assertEqual(snapshot["health"]["level"], "warning")
        # 原始诊断数据仍在遥测层，展示层过滤不更改它。
        self.assertEqual(len(await service.telemetry.diagnostic_alarms()), 3)


if __name__ == "__main__":
    unittest.main()
