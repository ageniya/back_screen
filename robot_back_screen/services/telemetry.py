"""Telemetry providers for offline development and ROS 2 robot deployment."""

from __future__ import annotations

import asyncio
import copy
import math
import os
import re
import subprocess
import threading
import time
from typing import Any


class MockTelemetryProvider:
    """Offline data only; it never controls or reads a real robot."""

    def __init__(self) -> None:
        self.mode = "mock"
        self._started_at = time.monotonic()
        self._soft_stopped = False

    async def snapshot(self) -> dict[str, Any]:
        elapsed_seconds = time.monotonic() - self._started_at
        uptime_seconds = int(elapsed_seconds)
        # 模拟实机连续关节流：约 20 秒完成一次双臂张开、合上的往返。
        # 数值为 URDF 关节使用的 ROS 弧度值，供背屏 3D 视图联调。
        arm_open_ratio = (math.sin(elapsed_seconds * 2 * math.pi / 20 - math.pi / 2) + 1) / 2
        shoulder_angle = 0.10 + 1.25 * arm_open_ratio
        elbow_angle = 0.08 + 0.32 * arm_open_ratio
        shoulder_deg = round(math.degrees(shoulder_angle), 1)
        elbow_deg = round(math.degrees(elbow_angle), 1)
        # 双臂 TCP 随张开动作产生小幅变化，便于联调状态页与 3D 视图。
        tcp_x = 1.23 + 0.28 * arm_open_ratio
        tcp_z = 0.56 + 0.12 * arm_open_ratio
        return {
            "robotModel": "R1-DEMO",
            "motion": {
                "position": "X1.23 Y2.34 Z0.56",
                "target": "X5.00 Y3.00 Z1.20",
                # 底盘保持原地，双臂在做模拟动作，因此底盘速度为零。
                "speed": "0.00 m/s",
                # tcp 保留给旧版调用方；新页面应使用左右手各自的 TCP。
                "tcp": f"X{tcp_x:.2f} Y2.34 Z{tcp_z:.2f}",
                "leftTcp": f"X{tcp_x:.2f} Y2.62 Z{tcp_z:.2f}",
                "rightTcp": f"X{tcp_x:.2f} Y2.06 Z{tcp_z:.2f}",
                # 状态页的六个关节摘要，同步反映双臂动作。
                "joints": [shoulder_deg, -shoulder_deg, elbow_deg, -elbow_deg, round(5 * arm_open_ratio, 1), round(-5 * arm_open_ratio, 1)],
                # URDF 关节名 -> 弧度值。用于背屏 3D 视图的离线联调：双臂张开。
                # 实机模式会直接用 ROS joint_states 的同名关节值替代。
                "jointPositions": {
                    "Lifting_Z": 0.12,
                    "Shoulder_X_L": shoulder_angle,
                    "Shoulder_X_R": -shoulder_angle,
                    "Shoulder_Y_L": 0.08 * arm_open_ratio,
                    "Shoulder_Y_R": -0.08 * arm_open_ratio,
                    "Shoulder_Z_L": 0.10 * arm_open_ratio,
                    "Shoulder_Z_R": -0.10 * arm_open_ratio,
                    "Elbow_L": -elbow_angle,
                    "Elbow_R": elbow_angle,
                },
            },
            "payloadKg": 2.3,
            "gripForceN": 12.5,
            "operationMode": "停止中" if self._soft_stopped else "自动",
            "uptime": f"{uptime_seconds // 3600}h{(uptime_seconds % 3600) // 60:02d}m",
            "battery": {
                "percent": 85,
                "remainingMinutes": 42,
                "voltage": 14.8,
                "current": 3.2,
                "temperature": 28,
                "cellVoltage": 3.70,
                "chargeStatus": "充电中",
                "cycles": 12,
            },
            "sensors": {
                "lidar": True,
                "depthCamera": True,
                "forceSensor": True,
                "bumper": "online",
                "camera": True,
                "network": True,
            },
            "network": {"ip": "192.168.1.10", "signalStrength": -55},
        }

    async def work_summary(self) -> dict[str, Any]:
        return {
            "lastChargeAh": 100,
            "triggerAh": 73.5,
            "lastChargeEndTs": 1754668800,
            "chargeStartTs": 1754695800,
            "ratedLoad": 50,
            "tasks": [
                {"name": "A 区搬运", "weight": 18.5, "time": "09:12"},
                {"name": "B 区搬运", "weight": 22.0, "time": "10:26"},
            ],
        }

    async def soft_stop(self) -> None:
        self._soft_stopped = True

    async def diagnostic_alarms(self) -> list[dict[str, Any]]:
        return []

    async def logs(self) -> list[dict[str, Any]]:
        """模拟模式没有机器人日志，避免把示例日志伪装成实机记录。"""
        return []

    async def connection_status(self) -> dict[str, Any]:
        """Make it explicit that these values are simulated, not real ROS."""
        return {
            "telemetryMode": "mock",
            "dataReady": False,
            "activeSources": [],
            "message": "当前使用模拟数据，尚未连接机器人 ROS 数据",
        }


class RosTelemetryProvider:
    """Read the documented NAVI ROS2 SDK main-branch interfaces.

    Imports are deliberately deferred: the ordinary development computer does
    not need ROS 2 or the robot message packages. This provider is only
    constructed when TELEMETRY_MODE=ros on the robot.
    """

    def __init__(self) -> None:
        try:
            import rclpy
            from diagnostic_msgs.msg import DiagnosticArray
            from geometry_msgs.msg import PoseStamped, WrenchStamped
            from nav_msgs.msg import Odometry
            from rclpy.node import Node
            from rclpy.qos import qos_profile_sensor_data
            from rcl_interfaces.msg import Log
            from sensor_msgs.msg import BatteryState, Image, JointState, LaserScan, PointCloud2
            from std_srvs.srv import Trigger
            try:
                from chassis_msgs.msg import AGVNewState
            except ImportError:
                AGVNewState = None
            # 标准消息可独立工作：即使机器人专有消息包尚未安装，也允许先接入
            # 已确认的 sensor_msgs/JointState 上肢仿真数据。
            RobotState = BasicInfo = Errors = Resource = WorkStatus = None
            # 现场存在同一话题名、不同消息包版本并存的情况：Orin 当前发布
            # robot_msgs/Resource，而 Pico 同时安装了 navi_robot_msgs。DDS 不会
            # 因字段看起来相同而自动匹配，因此保留旧版类型并同时订阅。
            LegacyErrors = LegacyResource = None
            try:
                # robot_jazzy 交付文档中的实际包名。
                from navi_robot_msgs.msg import Errors, Resource, RobotState
                from navi_robot_msgs.srv import BasicInfo
                try:
                    from navi_robot_msgs.msg import WorkStatus
                except ImportError:
                    pass
            except ImportError:
                try:
                    # 兼容少数旧镜像仍使用 robot_msgs 的情况。
                    from robot_msgs.msg import Errors, Resource, RobotState
                    from robot_msgs.srv import BasicInfo
                    try:
                        from robot_msgs.msg import WorkStatus
                    except ImportError:
                        pass
                except ImportError:
                    pass
            try:
                from robot_msgs.msg import Errors as LegacyErrors
                from robot_msgs.msg import Resource as LegacyResource
            except ImportError:
                pass
            try:
                # 已在 Pico 实机 ROS2 图谱中确认的上肢消息。
                from upperlimb_msgs.msg import Pose as UpperlimbPose
                from upperlimb_msgs.msg import UplimbState
            except ImportError:
                UpperlimbPose = UplimbState = None
        except ImportError as exc:
            raise RuntimeError(
                "ROS 模式需要在已安装 rclpy 和 ROS2 标准消息包的机器人环境中运行"
            ) from exc

        self.mode = "ros"
        self._rclpy = rclpy
        self._sensor_qos = qos_profile_sensor_data
        self._Log = Log
        self._Trigger = Trigger
        self._BasicInfo = BasicInfo
        self._Resource = Resource
        self._Errors = Errors
        self._LegacyResource = LegacyResource
        self._LegacyErrors = LegacyErrors
        self._UpperlimbPose = UpperlimbPose
        self._UplimbState = UplimbState
        self._WrenchStamped = WrenchStamped
        self._lock = threading.Lock()
        self._last_seen: dict[str, float] = {}
        # This answers the web UI's key question: has the process recently
        # received a ROS message, not merely started without an error?
        self._last_data_at: float | None = None
        self._active_sources: dict[str, float] = {}
        self._data_stale_seconds = float(os.getenv("ROS_DATA_STALE_SECONDS", "5"))
        self._diagnostic_alarms: list[dict[str, Any]] = []
        self._logs: list[dict[str, Any]] = []
        self._resource_error_flags: dict[str, bool] = {}
        # Pico 的 resource ROS 话题在当前镜像中没有发布者，但背屏服务
        # 就运行在 Pico 本机，可按需从 Linux /proc 与 sysfs 读取资源数据。
        self._local_resource_source = os.getenv("LOCAL_RESOURCE_SOURCE", "").strip().lower()
        self._last_cpu_times: tuple[int, int] | None = None
        self._sensor_timeout = float(os.getenv("ROS_SENSOR_TIMEOUT_SECONDS", "3"))
        self._network_interface = os.getenv("NETWORK_INTERFACE", "").strip()
        # 型号是设备身份，不应因为可选的 basic_info 服务暂时未启动就显示
        # unknown。部署时可用 ROBOT_MODEL 写入这台机器的已知型号；服务
        # 后续返回了实际型号时仍会覆盖这个兜底值。
        self._configured_robot_model = os.getenv("ROBOT_MODEL", "").strip() or None
        self._control_enabled = os.getenv("ROS_ENABLE_CONTROL", "false").strip().lower() == "true"
        self._snapshot: dict[str, Any] = {
            "robotModel": self._configured_robot_model,
            "motion": {"position": None, "target": None, "speed": None, "tcp": None, "leftTcp": None, "rightTcp": None, "joints": [None] * 6, "jointSummary": [], "jointPositions": {}},
            "payloadKg": None,
            "gripForceN": None,
            "operationMode": None,
            "upperLimbState": None,
            "uptime": None,
            "battery": {"percent": None, "remainingMinutes": None, "voltage": None, "current": None, "temperature": None, "cellVoltage": None, "chargeStatus": None, "cycles": None},
            "sensors": {
                "lidar": None, "lidar1": None, "lidar2": None,
                "depthCamera": None, "camera": None, "headCamera": None,
                "leftWristCamera": None, "rightWristCamera": None,
                "forceSensor": None, "bumper": None, "network": None,
            },
            "network": {"ip": None, "signalStrength": None},
            # 手部与腕部数据单独保存：它们是已确认的真实 Pico 接口，但不应
            # 冒充上肢六轴关节或夹持力。
            "hands": {"left": {"jointPositions": {}, "effort": {}}, "right": {"jointPositions": {}, "effort": {}}},
            "wristForces": {"left": None, "right": None},
        }

        if not rclpy.ok():
            rclpy.init(args=None)
        self._node: Node = Node("robot_diagnostics_service")
        robot_name = os.getenv("ROBOT_NAME", "").strip().strip("/")
        configured_ns = os.getenv("ROS_NAMESPACE", "").strip().strip("/")
        ns = "/" + (configured_ns or robot_name or "zj_humanoid")

        # Pico Robot publishes battery_state; WA chassis publishes battery_info.
        # Orin 当前镜像还会把底盘 Web 桥接数据发布在 /web/*。两类话题都
        # 可以通过环境变量补充，避免把某一版中间件的固定命名写死在代码里。
        def configured_topics(env_name: str, defaults: list[str]) -> list[str]:
            extras = [item.strip() for item in os.getenv(env_name, "").split(",") if item.strip()]
            return list(dict.fromkeys([*defaults, *extras]))

        for topic in configured_topics(
            "ROS_BATTERY_TOPICS",
            [f"{ns}/robot/battery_state", f"{ns}/robot/battery_info"],
        ):
            self._node.create_subscription(BatteryState, topic, self._on_battery, 10)
        for topic in configured_topics("ROS_ODOM_TOPICS", ["/chassis/odom_info", f"{ns}/chassis/odom_info"]):
            self._node.create_subscription(Odometry, topic, self._on_odom, 10)
        if AGVNewState is not None:
            for topic in configured_topics("ROS_CHASSIS_STATE_TOPICS", ["/chassis/agv_state"]):
                self._node.create_subscription(AGVNewState, topic, self._on_chassis_state, 10)
        else:
            self._node.get_logger().warning("缺少 chassis_msgs/AGVNewState，底盘电池与碰撞状态暂不可解码")
        if RobotState is not None:
            self._node.create_subscription(RobotState, f"{ns}/robot/robot_state", self._on_robot_state, 10)
        # 上肢/作业接口不在当前实际对外文档中。只有接机确认 topic 后再通过
        # 环境变量开启，避免部署时静默订阅一个猜测出来的名称。
        work_status_topic = os.getenv("ROS_WORK_STATUS_TOPIC", "").strip()
        if WorkStatus is not None and work_status_topic:
            self._node.create_subscription(WorkStatus, work_status_topic, self._on_work_status, 10)
        joint_states_topic = os.getenv("ROS_JOINT_STATES_TOPIC", "").strip()
        if joint_states_topic:
            self._node.create_subscription(JointState, joint_states_topic, self._on_joint_states, 10)
        # Pico 已确认的真实手部接口。手部关节与上肢 JointState 分开保存，
        # 避免用手指角度覆盖 3D 上肢姿态。
        self._node.create_subscription(JointState, f"{ns}/hand/joint_states", self._on_hand_joint_states, 10)
        self._node.create_subscription(WrenchStamped, f"{ns}/hand/wrist_force_sensor/left", lambda message: self._on_wrist_force("left", message), 10)
        self._node.create_subscription(WrenchStamped, f"{ns}/hand/wrist_force_sensor/right", lambda message: self._on_wrist_force("right", message), 10)
        self._node.create_subscription(JointState, f"{ns}/robot/joint_motor/temperatures", self._on_joint_temperatures, 10)
        self._node.create_subscription(JointState, f"{ns}/robot/joint_motor/errors", self._on_joint_errors, 10)
        tcp_pose_topic = os.getenv("ROS_TCP_POSE_TOPIC", "").strip()
        if tcp_pose_topic:
            self._node.create_subscription(PoseStamped, tcp_pose_topic, self._on_tcp_pose, 10)
        # 双臂接口已在当前 ROS2 图谱确认；以环境变量指定命名空间，便于从
        # /fake/upperlimb 无缝切换到未来实机的 /<ROBOT_NAME>/upperlimb。
        left_tcp_topic = os.getenv("ROS_LEFT_TCP_TOPIC", "").strip()
        right_tcp_topic = os.getenv("ROS_RIGHT_TCP_TOPIC", "").strip()
        if UpperlimbPose is not None and left_tcp_topic:
            self._node.create_subscription(UpperlimbPose, left_tcp_topic, lambda message: self._on_arm_tcp_pose("leftTcp", message), 10)
        if UpperlimbPose is not None and right_tcp_topic:
            self._node.create_subscription(UpperlimbPose, right_tcp_topic, lambda message: self._on_arm_tcp_pose("rightTcp", message), 10)
        upperlimb_state_topic = os.getenv("ROS_UPPERLIMB_STATE_TOPIC", "").strip()
        if UplimbState is not None and upperlimb_state_topic:
            self._node.create_subscription(UplimbState, upperlimb_state_topic, self._on_uplimb_state, 10)
        # 诊断汇总的命名在不同交付版本中不同。订阅已知路径和部署时显式
        # 配置的路径；没有发布者时不会产生虚假告警。
        configured_diagnostic_topics = os.getenv("ROS_DIAGNOSTICS_TOPICS", "").strip()
        diagnostic_topics = (
            [item.strip() for item in configured_diagnostic_topics.split(",") if item.strip()]
            if configured_diagnostic_topics
            else [
                "/diagnostics_agg",
                f"{ns}/robot/orin_states/diagnostics_agg",
                f"{ns}/robot/pico_states/diagnostics_agg",
            ]
        )
        for diagnostic_topic in dict.fromkeys(diagnostic_topics):
            self._node.create_subscription(DiagnosticArray, diagnostic_topic, self._on_diagnostics, 10)
        # /rosout 是 ROS2 标准日志流。只读订阅，最多保留最近 200 条，避免
        # 长时间运行时无限占用内存。
        self._node.create_subscription(Log, "/rosout", self._on_ros_log, 100)
        # chassis 文档已确认 WA1 的 2D 激光接口；PointCloud2 只在明确配置时订阅。
        lidar_1_topic = os.getenv("ROS_LIDAR_1_TOPIC", "").strip() or os.getenv("ROS_LASER_SCAN_TOPIC", f"{ns}/chassis/laser_scan")
        lidar_2_topic = os.getenv("ROS_LIDAR_2_TOPIC", "").strip()
        if lidar_1_topic:
            self._node.create_subscription(LaserScan, lidar_1_topic, lambda _: self._mark_seen("lidar1"), self._sensor_qos)
        if lidar_2_topic:
            self._node.create_subscription(LaserScan, lidar_2_topic, lambda _: self._mark_seen("lidar2"), self._sensor_qos)
        pointcloud_topic = os.getenv("ROS_LIDAR_POINTCLOUD_TOPIC", "").strip()
        if pointcloud_topic:
            self._node.create_subscription(PointCloud2, pointcloud_topic, lambda _: self._mark_seen("lidar"), self._sensor_qos)

        # Orin 与 Pico 的资源话题名称不同。两个订阅可并存，只有实机实际发布的
        # 那一路会回调，不需要在部署前猜测设备类型。
        if Resource is not None:
            self._node.create_subscription(Resource, f"{ns}/robot/orin_states/resource", lambda message: self._on_resource(message, "orin"), 10)
            self._node.create_subscription(Resource, f"{ns}/robot/pico_states/resource", lambda message: self._on_resource(message, "pico"), 10)
        if LegacyResource is not None and LegacyResource is not Resource:
            self._node.create_subscription(LegacyResource, f"{ns}/robot/orin_states/resource", lambda message: self._on_resource(message, "orin"), 10)
            self._node.create_subscription(LegacyResource, f"{ns}/robot/pico_states/resource", lambda message: self._on_resource(message, "pico"), 10)
        if Errors is not None:
            self._node.create_subscription(Errors, f"{ns}/robot/orin_states/errors", lambda message: self._on_resource_errors(message, "orin"), 10)
            self._node.create_subscription(Errors, f"{ns}/robot/pico_states/errors", lambda message: self._on_resource_errors(message, "pico"), 10)
        if LegacyErrors is not None and LegacyErrors is not Errors:
            self._node.create_subscription(LegacyErrors, f"{ns}/robot/orin_states/errors", lambda message: self._on_resource_errors(message, "orin"), 10)
            self._node.create_subscription(LegacyErrors, f"{ns}/robot/pico_states/errors", lambda message: self._on_resource_errors(message, "pico"), 10)

        # 背屏只需要相机在线状态，不展示图像画面。若订阅 Image，即使回调
        # 什么也不做，Python 仍会反序列化每一张高带宽图像，Pico 会明显卡顿。
        # 改为低频检查各话题是否有发布者，显示“相机驱动/话题在线”。
        depth_topic = os.getenv("ROS_DEPTH_CAMERA_TOPIC", "").strip()
        camera_topic = os.getenv("ROS_CAMERA_TOPIC", "").strip()
        # 左腕彩色相机是当前实机已经确认的话题；默认纳入在线检测，仍可通过
        # 环境变量覆盖。这里只检查发布者，不订阅高带宽图像帧。
        left_wrist_camera_topic = os.getenv(
            "ROS_LEFT_WRIST_CAMERA_TOPIC", f"{ns}/sensor/left_wrist/color/image_raw"
        ).strip()
        # 左右腕相机均已在 Pico 实机确认，默认纳入在线检测。背屏只查询
        # 发布者状态，不订阅 Image 内容，避免影响 Pico 的渲染和总线带宽。
        right_wrist_camera_topic = os.getenv(
            "ROS_RIGHT_WRIST_CAMERA_TOPIC", f"{ns}/sensor/right_wrist/color/image_raw"
        ).strip()
        self._camera_topics = {
            name: topic for name, topic in {
                "depthCamera": depth_topic,
                "headCamera": camera_topic,
                "leftWristCamera": left_wrist_camera_topic,
                "rightWristCamera": right_wrist_camera_topic,
            }.items() if topic
        }
        if self._camera_topics:
            self._refresh_camera_publishers()
            self._node.create_timer(2.0, self._refresh_camera_publishers)

        self._basic_info_client = self._node.create_client(BasicInfo, f"{ns}/robot/basic_info") if BasicInfo is not None else None
        self._stop_service = os.getenv("ROS_STOP_SERVICE", f"{ns}/robot/stop").strip()
        self._stop_client = self._node.create_client(Trigger, self._stop_service)
        self._request_basic_info()
        # 服务可能晚于背屏后端启动；周期重试而不是只在启动瞬间尝试一次。
        if self._basic_info_client is not None:
            self._node.create_timer(5.0, self._request_basic_info)
        self._node.create_timer(2.0, self._refresh_network)
        if self._local_resource_source == "pico":
            self._node.create_timer(3.0, self._refresh_local_pico_resource)
        self._spin_thread = threading.Thread(target=self._spin, name="robot-diagnostics-ros", daemon=True)
        self._spin_thread.start()

    @staticmethod
    def _number(value: Any) -> float | None:
        try:
            number = float(value)
            return number if math.isfinite(number) else None
        except (TypeError, ValueError):
            return None

    def _spin(self) -> None:
        self._rclpy.spin(self._node)

    def _mark_seen(self, name: str) -> None:
        with self._lock:
            self._mark_seen_locked(name)

    def _mark_data_received_locked(self, source: str) -> None:
        now = time.monotonic()
        self._last_data_at = now
        self._active_sources[source] = now

    def _mark_seen_locked(self, name: str, *, counts_as_robot_data: bool = True) -> None:
        self._last_seen[name] = time.monotonic()
        if counts_as_robot_data:
            self._mark_data_received_locked(name)

    def _refresh_network(self) -> None:
        """Read the local NIC state; it never changes robot configuration."""
        interface = self._network_interface
        try:
            if not interface:
                route_parts = subprocess.run(
                    ["ip", "route", "show", "default"],
                    capture_output=True, text=True, timeout=1, check=False,
                ).stdout.split()
                interface = route_parts[route_parts.index("dev") + 1] if "dev" in route_parts else ""
            if not interface:
                return
            link_state = subprocess.run(
                ["cat", f"/sys/class/net/{interface}/operstate"],
                capture_output=True, text=True, timeout=1, check=False,
            ).stdout.strip().lower()
            address_lines = subprocess.run(
                ["ip", "-o", "-4", "addr", "show", "dev", interface],
                capture_output=True, text=True, timeout=1, check=False,
            ).stdout.splitlines()
            ip_address = None
            for line in address_lines:
                parts = line.split()
                if "inet" in parts:
                    ip_address = parts[parts.index("inet") + 1].split("/")[0]
                    break
            online = link_state == "up" and ip_address is not None
        except (OSError, subprocess.SubprocessError, ValueError, IndexError):
            return
        with self._lock:
            self._snapshot["network"]["ip"] = ip_address
            self._snapshot.setdefault("diagnosticMetrics", {})["network"] = {
                "interface": interface,
                "linkState": link_state or "unknown",
            }
            if online:
                # 本机网卡在线只能说明运行背屏的电脑联网，不能代表已经
                # 收到了机器人 ROS 消息，更不能使页面显示“数据已接入”。
                self._mark_seen_locked("network", counts_as_robot_data=False)
            else:
                self._last_seen["network"] = time.monotonic() - self._sensor_timeout - 1

    def _refresh_camera_publishers(self) -> None:
        """Lightweight camera availability check; deliberately does not read images."""
        for name, topic in self._camera_topics.items():
            try:
                online = self._node.count_publishers(topic) > 0
            except Exception:
                continue
            with self._lock:
                if online:
                    # 这里只检查 ROS 图里是否存在相机发布者，没有读取任何
                    # 图像帧；它是传感器在线提示，不作为实机数据接收依据。
                    self._mark_seen_locked(name, counts_as_robot_data=False)
                else:
                    self._last_seen[name] = time.monotonic() - self._sensor_timeout - 1

    def _refresh_local_pico_resource(self) -> None:
        """Read Pico's own Linux resource usage when its ROS resource topic is absent."""
        try:
            cpu_line = open("/proc/stat", encoding="utf-8").readline().split()
            cpu_values = [int(value) for value in cpu_line[1:]]
            total = sum(cpu_values)
            idle = cpu_values[3] + (cpu_values[4] if len(cpu_values) > 4 else 0)
            cpu_usage = None
            if self._last_cpu_times is not None:
                previous_total, previous_idle = self._last_cpu_times
                total_delta, idle_delta = total - previous_total, idle - previous_idle
                if total_delta > 0:
                    cpu_usage = round(100.0 * (1.0 - idle_delta / total_delta), 2)
            self._last_cpu_times = (total, idle)

            memory_values: dict[str, int] = {}
            for line in open("/proc/meminfo", encoding="utf-8"):
                key, value = line.split(":", 1)
                memory_values[key] = int(value.strip().split()[0])
            total_memory = memory_values.get("MemTotal", 0)
            available_memory = memory_values.get("MemAvailable", 0)
            memory_usage = round(100.0 * (1.0 - available_memory / total_memory), 2) if total_memory else None

            disk = os.statvfs("/")
            disk_usage = round(100.0 * (1.0 - disk.f_bavail / disk.f_blocks), 2) if disk.f_blocks else None
            temperatures = []
            for zone in range(32):
                path = f"/sys/class/thermal/thermal_zone{zone}/temp"
                if not os.path.exists(path):
                    continue
                raw = self._number(open(path, encoding="utf-8").read().strip())
                if raw is not None:
                    temperatures.append(raw / 1000.0 if raw > 1000 else raw)
            temperature = round(max(temperatures), 2) if temperatures else None
        except (OSError, ValueError, IndexError):
            return

        metrics = {
            "cpuUsage": cpu_usage,
            "memoryUsage": memory_usage,
            "diskUsage": disk_usage,
            "temperature": temperature,
            "gpuUsage": None,
        }
        flags = {
            "overTemperature": bool(temperature is not None and temperature >= 80),
            "overCpu": bool(cpu_usage is not None and cpu_usage >= 90),
            "overMemory": bool(memory_usage is not None and memory_usage >= 90),
            "overDisk": bool(disk_usage is not None and disk_usage >= 90),
        }
        with self._lock:
            self._mark_data_received_locked("pico_resource")
            store = self._snapshot.setdefault("diagnosticMetrics", {})
            store["picoResource"] = metrics
            store["picoResourceErrors"] = flags

    def _on_battery(self, message: Any) -> None:
        percent = self._number(message.percentage)
        voltage = self._number(message.voltage)
        current = self._number(message.current)
        temperature = self._number(message.temperature)
        cell_values = [value for value in (self._number(item) for item in getattr(message, "cell_voltage", [])) if value is not None]
        status_names = {0: "未知", 1: "充电中", 2: "放电中", 3: "未充电", 4: "已充满"}
        # 实机 BMS 未完成初始化时会发布一帧 BatteryState 默认值：电量、
        # 电压、电流均为 0，temperature 甚至可能是未初始化内存中的极大数。
        # 已上电机器人不可能有 0V 电池包，因此将这一整帧视为“无有效数据”，
        # 让页面显示 --，避免误导为电池真的耗尽或温度异常。
        valid_pack = voltage is not None and voltage > 1.0
        if not valid_pack:
            percent = voltage = current = temperature = None
            cell_values = []
        elif temperature is not None and not -40.0 <= temperature <= 100.0:
            # BatteryState 的温度单位为 °C；超出工程可用范围的值直接丢弃。
            temperature = None
        charge_status = status_names.get(int(message.power_supply_status), "未知") if valid_pack else None
        with self._lock:
            if not valid_pack:
                chassis_battery_at = self._active_sources.get("chassis_battery")
                if chassis_battery_at is not None and time.monotonic() - chassis_battery_at <= self._data_stale_seconds:
                    return
            if valid_pack:
                self._mark_data_received_locked("battery")
            self._snapshot["battery"].update({
                "percent": round(percent * 100, 1) if percent is not None else None,
                "voltage": voltage,
                "current": current,
                "temperature": temperature,
                "cellVoltage": round(sum(cell_values) / len(cell_values), 3) if cell_values else None,
                "chargeStatus": charge_status,
            })

    def _on_chassis_state(self, message: Any) -> None:
        """读取实机底盘状态；电量比例为 0~1，不推测温度或充电状态。"""
        voltage = self._number(message.battery_voltage)
        current = self._number(message.battery_current)
        percent = self._number(message.battery_percentage)
        if percent is not None and not 0.0 <= percent <= 1.0:
            percent = None
        with self._lock:
            self._mark_data_received_locked("chassis_state")
            self._snapshot.setdefault("diagnosticMetrics", {})["chassisState"] = {
                "code": int(message.state),
                "description": str(message.description),
                "emergency": bool(message.emergency),
                "collision": bool(message.collision),
            }
            if voltage is not None and voltage > 1.0:
                self._mark_data_received_locked("chassis_battery")
                self._snapshot["battery"].update({
                    "percent": round(percent * 100, 1) if percent is not None else None,
                    "voltage": voltage,
                    "current": current,
                })

    def _on_robot_state(self, message: Any) -> None:
        state_info = str(getattr(message, "state_info", ""))
        state_names = {
            0: "未初始化", 1: "配置中", 2: "已上电", 3: "启动中", 4: "初始化中",
            5: "运行中", 6: "暂停", 7: "停止", 8: "已关机", 9: "异常",
        }
        state = getattr(message, "state", None)
        label = state_names.get(state, "")
        with self._lock:
            self._mark_data_received_locked("robot_state")
            self._snapshot["operationMode"] = label or state_info or None
            self._snapshot.setdefault("diagnosticMetrics", {})["robotState"] = {
                "code": state,
                "info": state_info,
            }

    def _on_work_status(self, message: Any) -> None:
        mode = str(getattr(message, "mode", ""))
        with self._lock:
            self._mark_data_received_locked("work_status")
            if mode:
                self._snapshot["operationMode"] = mode

    def _on_odom(self, message: Any) -> None:
        position = message.pose.pose.position
        velocity = message.twist.twist.linear
        speed = math.sqrt(velocity.x ** 2 + velocity.y ** 2 + velocity.z ** 2)
        with self._lock:
            self._mark_data_received_locked("odometry")
            self._snapshot["motion"]["position"] = f"X{position.x:.2f} Y{position.y:.2f} Z{position.z:.2f}"
            self._snapshot["motion"]["speed"] = f"{speed:.2f} m/s"

    def _on_resource(self, message: Any, source: str = "orin") -> None:
        """接收 robot_jazzy 文档定义的 Orin/Pico 资源快照。"""
        metrics = {
            "cpuUsage": self._number(getattr(message, "cpu_usage", None)),
            "memoryUsage": self._number(getattr(message, "memory_usage", None)),
            "diskUsage": self._number(getattr(message, "disk_usage", None)),
            "temperature": self._number(getattr(message, "temperature", None)),
            "gpuUsage": self._number(getattr(message, "gpu_usage", None)),
        }
        with self._lock:
            # Orin 与 Pico 资源必须分别记录新鲜度。否则 Pico 节点停止
            # 发布后，界面会一直显示内存中遗留的旧资源数值。
            source_key = "system_resource" if source == "orin" else "pico_resource"
            self._mark_data_received_locked(source_key)
            metrics_store = self._snapshot.setdefault("diagnosticMetrics", {})
            average_cpu = None
            if source == "orin" and metrics_store.get("systemResourceCpuSource") == "diagnostics_average":
                average_cpu = metrics_store.get("systemResource", {}).get("cpuUsage")
            metrics_store["systemResource" if source == "orin" else "picoResource"] = metrics
            # Orin 的 resource.cpu_usage 是各核心最大值；若诊断话题已经
            # 计算出平均值，不要让后到达的 resource 消息把它覆盖回最大值。
            if average_cpu is not None:
                metrics_store["systemResource"]["cpuUsage"] = average_cpu

    def _on_resource_errors(self, message: Any, source: str = "orin") -> None:
        flags = {
            "overTemperature": bool(getattr(message, "over_temp", False)),
            "overCpu": bool(getattr(message, "over_cpu", False)),
            "overMemory": bool(getattr(message, "over_mem", False)),
            "overDisk": bool(getattr(message, "over_disk", False)),
        }
        with self._lock:
            source_key = "system_resource_errors" if source == "orin" else "pico_resource_errors"
            self._mark_data_received_locked(source_key)
            self._resource_error_flags = flags
            metrics_store = self._snapshot.setdefault("diagnosticMetrics", {})
            metrics_store["systemResourceErrors" if source == "orin" else "picoResourceErrors"] = flags

    def _on_joint_states(self, message: Any) -> None:
        raw_positions = list(getattr(message, "position", []))
        values = [round(math.degrees(value), 1) for value in raw_positions[:6]]
        names = list(getattr(message, "name", []))
        # 3D 视图需要 URDF 原始关节名和 ROS 弧度值；状态页仍保留前六个角度的度数显示。
        joint_positions = {
            str(name): float(value)
            for name, value in zip(names, raw_positions)
            if self._number(value) is not None
        }
        # 状态页紧凑摘要保留来源关节名，不能把真实关节顺序误标成 J1～J6。
        joint_summary = [
            {"name": str(name), "degrees": round(math.degrees(value), 1)}
            for name, value in zip(names[:6], raw_positions[:6])
            if self._number(value) is not None
        ]
        with self._lock:
            self._mark_data_received_locked("joint_states")
            self._snapshot["motion"]["joints"] = values + [None] * (6 - len(values))
            self._snapshot["motion"]["jointSummary"] = joint_summary
            self._snapshot["motion"]["jointPositions"] = joint_positions

    def _on_hand_joint_states(self, message: Any) -> None:
        """保存 Pico 实际发布的左右手手指关节，单位保留为 ROS 弧度。"""
        names = list(getattr(message, "name", []))
        positions = list(getattr(message, "position", []))
        efforts = list(getattr(message, "effort", []))
        hands = {"left": {"jointPositions": {}, "effort": {}}, "right": {"jointPositions": {}, "effort": {}}}
        for index, name in enumerate(names):
            joint_name = str(name)
            side = "left" if joint_name.endswith("_LEFT") else "right" if joint_name.endswith("_RIGHT") else None
            if side is None:
                continue
            position = self._number(positions[index] if index < len(positions) else None)
            effort = self._number(efforts[index] if index < len(efforts) else None)
            if position is not None:
                hands[side]["jointPositions"][joint_name] = position
            if effort is not None:
                hands[side]["effort"][joint_name] = effort
        with self._lock:
            self._mark_data_received_locked("hand_joint_states")
            self._snapshot["hands"] = hands

    def _on_wrist_force(self, side: str, message: Any) -> None:
        """保存腕部六维力；这是力/力矩测量，不等同于夹爪夹持力。"""
        wrench = getattr(message, "wrench", None)
        force = getattr(wrench, "force", None)
        torque = getattr(wrench, "torque", None)
        if force is None or torque is None:
            return
        values = {
            "force": {axis: self._number(getattr(force, axis, None)) for axis in ("x", "y", "z")},
            "torque": {axis: self._number(getattr(torque, axis, None)) for axis in ("x", "y", "z")},
        }
        with self._lock:
            self._mark_seen_locked("forceSensor")
            self._mark_data_received_locked(f"{side}_wrist_force")
            self._snapshot["wristForces"][side] = values

    def _on_joint_temperatures(self, message: Any) -> None:
        temperatures = [self._number(value) for value in list(getattr(message, "effort", []))]
        known = [value for value in temperatures if value is not None]
        if known:
            with self._lock:
                self._mark_data_received_locked("joint_temperature")
                self._snapshot.setdefault("diagnosticMetrics", {})["maxJointTemperature"] = max(known)

    def _on_joint_errors(self, message: Any) -> None:
        errors = [self._number(value) for value in list(getattr(message, "effort", []))]
        with self._lock:
            self._mark_data_received_locked("joint_errors")
            self._snapshot.setdefault("diagnosticMetrics", {})["jointErrorCodes"] = errors

    def _on_tcp_pose(self, message: Any) -> None:
        position = message.pose.position
        with self._lock:
            self._mark_data_received_locked("tcp_pose")
            self._snapshot["motion"]["tcp"] = f"X{position.x:.2f} Y{position.y:.2f} Z{position.z:.2f}"

    def _format_tcp(self, message: Any) -> str | None:
        """从上肢 Pose 中提取 XYZ，兼容交付版本的常见嵌套形式。"""
        candidates = [
            message,
            getattr(message, "position", None),
            getattr(message, "pose", None),
            getattr(getattr(message, "pose", None), "position", None),
        ]
        for position in candidates:
            if position is None:
                continue
            x = self._number(getattr(position, "x", None))
            y = self._number(getattr(position, "y", None))
            z = self._number(getattr(position, "z", None))
            if x is not None and y is not None and z is not None:
                return f"X{x:.2f} Y{y:.2f} Z{z:.2f}"
        return None

    def _on_arm_tcp_pose(self, side: str, message: Any) -> None:
        tcp = self._format_tcp(message)
        if tcp is None:
            return
        with self._lock:
            self._mark_data_received_locked(side)
            self._snapshot["motion"][side] = tcp

    def _on_uplimb_state(self, message: Any) -> None:
        """保存上肢控制器的真实状态，不把它误标为自动/手动运行模式。"""
        state = {
            "commandNumber": self._number(getattr(message, "cmd_num", None)),
            "commandName": str(getattr(message, "cmd_name", "")) or None,
            "leftArmSingular": bool(getattr(message, "left_arm_is_singular", False)),
            "rightArmSingular": bool(getattr(message, "right_arm_is_singular", False)),
            "iddpStatus": bool(getattr(message, "iddp_status", False)),
        }
        with self._lock:
            self._mark_data_received_locked("upperlimb_state")
            self._snapshot["upperLimbState"] = state

    def _on_diagnostics(self, message: Any) -> None:
        severity = {1: "warning", 2: "critical", 3: "critical"}
        alarms = []
        # Jetson 诊断话题给出每个 CPU 核心的占用率；不要把第一个核心
        # 或 resource 话题中的“最大值”当成整机 CPU。这里计算所有核心平均值。
        cpu_values = []
        for index, status in enumerate(message.status):
            status_name = str(getattr(status, "name", ""))
            if status_name.startswith("/jtop/CPU/cpu"):
                raw_cpu = str(getattr(status, "message", ""))
                if not raw_cpu:
                    for item in getattr(status, "values", []) or []:
                        if str(getattr(item, "key", "")) == "Val":
                            raw_cpu = str(getattr(item, "value", ""))
                            break
                match = re.search(r"[-+]?\d+(?:\.\d+)?", raw_cpu)
                if match:
                    value = self._number(match.group(0))
                    if value is not None and 0 <= value <= 100:
                        cpu_values.append(value)
            raw_level = status.level
            # ROS2 的 uint8 在不同生成版本中可能表现为 int 或单字节 bytes。
            # 诊断回调必须兼容两种表示，避免一条正常 level=0 消息使订阅线程退出。
            if isinstance(raw_level, bytes):
                level = raw_level[0] if raw_level else 0
            else:
                try:
                    level = int(raw_level)
                except (TypeError, ValueError):
                    level = 0
            if level == 0:
                continue
            alarms.append({
                "id": f"ros-{index}-{status.name}",
                "code": f"ROS-{level}",
                "severity": severity.get(level, "warning"),
                "title": status.name or "系统诊断异常",
                "time": time.strftime("%Y-%m-%d %H:%M:%S"),
                "desc": status.message or "ROS 诊断汇总发现异常",
                "suggestion": "请检查对应诊断模块和设备状态",
                "occurrenceCount": 1,
                "label": "ROS 诊断汇总",
                "values": [],
            })
        with self._lock:
            self._mark_data_received_locked("diagnostics")
            self._diagnostic_alarms = alarms
            if cpu_values:
                metrics = self._snapshot.setdefault("diagnosticMetrics", {}).setdefault("systemResource", {})
                metrics["cpuUsage"] = round(sum(cpu_values) / len(cpu_values), 2)
                self._snapshot["diagnosticMetrics"]["systemResourceCpuSource"] = "diagnostics_average"

    def _on_ros_log(self, message: Any) -> None:
        raw_level = getattr(message, "level", 20)
        # 不同 ROS Python 绑定对 uint8 的表示可能是 int 或单字节 bytes。
        level = raw_level[0] if isinstance(raw_level, bytes) and raw_level else int(raw_level)
        level_map = {
            10: ("info", "调试"),
            20: ("info", "信息"),
            30: ("warn", "警告"),
            40: ("fault", "错误"),
            50: ("fault", "致命错误"),
        }
        log_type, label = level_map.get(level, ("info", "信息"))
        entry = {
            "time": time.strftime("%H:%M:%S"),
            "type": log_type,
            "label": label,
            "text": str(getattr(message, "msg", "")) or "ROS 节点输出空日志",
            "source": str(getattr(message, "name", "ROS")) or "ROS",
        }
        with self._lock:
            self._mark_data_received_locked("rosout")
            self._logs.insert(0, entry)
            del self._logs[200:]

    def _request_basic_info(self) -> None:
        if self._basic_info_client is None or self._BasicInfo is None:
            return
        if not self._basic_info_client.wait_for_service(timeout_sec=0.1):
            return
        future = self._basic_info_client.call_async(self._BasicInfo.Request())

        def save_result(result_future: Any) -> None:
            try:
                result = result_future.result()
            except Exception:
                return
            if not getattr(result, "success", False):
                return
            with self._lock:
                # 空字符串代表服务没有提供型号，保留部署配置的已知型号。
                self._snapshot["robotModel"] = result.robot_model or self._configured_robot_model
                self._snapshot["network"]["ip"] = result.ip_address or None

        future.add_done_callback(save_result)

    async def snapshot(self) -> dict[str, Any]:
        now = time.monotonic()
        with self._lock:
            snapshot = copy.deepcopy(self._snapshot)
            for name in snapshot["sensors"]:
                seen_at = self._last_seen.get(name)
                snapshot["sensors"][name] = None if seen_at is None else now - seen_at <= self._sensor_timeout
            chassis_at = self._active_sources.get("chassis_state")
            chassis = snapshot.get("diagnosticMetrics", {}).get("chassisState")
            if chassis and chassis_at is not None:
                fresh = now - chassis_at <= self._sensor_timeout
                snapshot["sensors"]["bumper"] = ("triggered" if chassis["collision"] else "online") if fresh else False
                if not fresh:
                    snapshot["diagnosticMetrics"].pop("chassisState", None)
            # 关节、TCP 都是瞬时状态。发布者停止后不能把最后一帧（常见为
            # 全 0 的停机帧）继续冒充实时姿态，应明确交给页面显示为 --。
            motion = snapshot.get("motion")
            if isinstance(motion, dict):
                odom_at = self._active_sources.get("odometry")
                if odom_at is None or now - odom_at > self._data_stale_seconds:
                    motion["position"] = motion["speed"] = None
                joint_at = self._active_sources.get("joint_states")
                if joint_at is None or now - joint_at > self._data_stale_seconds:
                    motion["joints"] = [None] * 6
                    motion["jointSummary"] = []
                    motion["jointPositions"] = {}
                for source, field in (("leftTcp", "leftTcp"), ("rightTcp", "rightTcp")):
                    seen_at = self._active_sources.get(source)
                    if seen_at is None or now - seen_at > self._data_stale_seconds:
                        motion[field] = None
            upper_limb_at = self._active_sources.get("upperlimb_state")
            if upper_limb_at is None or now - upper_limb_at > self._data_stale_seconds:
                snapshot["upperLimbState"] = None
            battery_at = max(self._active_sources.get("battery", 0), self._active_sources.get("chassis_battery", 0))
            if now - battery_at > self._data_stale_seconds:
                for field in ("percent", "voltage", "current", "temperature", "cellVoltage", "chargeStatus"):
                    snapshot["battery"][field] = None
            elif now - self._active_sources.get("battery", 0) > self._data_stale_seconds:
                # AGVNewState 只有三项电池读数，不能延续过期 BatteryState 的其它字段。
                for field in ("temperature", "cellVoltage", "chargeStatus"):
                    snapshot["battery"][field] = None
            # Pico 资源未持续发布时，不把上一次缓存误报为实时数据。
            pico_resource_at = self._active_sources.get("pico_resource")
            if pico_resource_at is None or now - pico_resource_at > self._data_stale_seconds:
                metrics = snapshot.get("diagnosticMetrics")
                if isinstance(metrics, dict):
                    metrics.pop("picoResource", None)
                    metrics.pop("picoResourceErrors", None)
        return snapshot

    async def connection_status(self) -> dict[str, Any]:
        """Report whether this adapter is receiving fresh ROS messages."""
        now = time.monotonic()
        with self._lock:
            age = None if self._last_data_at is None else round(now - self._last_data_at, 1)
            data_ready = age is not None and age <= self._data_stale_seconds
            active_sources = sorted(
                source for source, seen_at in self._active_sources.items()
                if now - seen_at <= self._data_stale_seconds
            )
        source_kind = os.getenv("ROS_DATA_SOURCE", "robot").strip().lower()
        is_simulation = source_kind in {"simulation", "sim", "fake"}
        return {
            "telemetryMode": "ros",
            "dataSource": "simulation" if is_simulation else "robot",
            "dataReady": data_ready,
            "lastMessageAgeSeconds": age,
            "activeSources": active_sources,
            "message": (
                "已收到 ROS 上肢测试数据" if is_simulation and data_ready
                else "已收到 ROS 实机数据" if data_ready
                else "ROS 已启动，等待机器人数据"
            ),
        }

    async def work_summary(self) -> dict[str, Any]:
        return {"lastChargeAh": None, "triggerAh": None, "lastChargeEndTs": None, "chargeStartTs": None, "ratedLoad": None, "tasks": []}

    async def diagnostic_alarms(self) -> list[dict[str, Any]]:
        with self._lock:
            alarms = copy.deepcopy(self._diagnostic_alarms)
            error_flags = copy.deepcopy(self._resource_error_flags)
        error_labels = {
            "overTemperature": ("资源温度过高", "请检查 Orin 散热、风扇和环境温度"),
            "overCpu": ("系统资源 CPU 过高", "请检查高负载进程与 CPU 占用"),
            "overMemory": ("系统内存占用过高", "请检查内存占用与长期运行的进程"),
            "overDisk": ("系统磁盘空间不足", "请清理日志或扩容存储空间"),
        }
        for key, (title, suggestion) in error_labels.items():
            if error_flags.get(key):
                alarms.append({
                    "id": f"resource-{key}",
                    "code": f"RESOURCE-{key}",
                    "severity": "warning",
                    "title": title,
                    "time": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "desc": "Orin 资源监控已报告此状态。",
                    "suggestion": suggestion,
                    "occurrenceCount": 1,
                    "label": "Orin 系统资源",
                    "values": [],
                })
        return alarms

    async def logs(self) -> list[dict[str, Any]]:
        with self._lock:
            return copy.deepcopy(self._logs)

    async def soft_stop(self) -> None:
        if not self._control_enabled:
            raise PermissionError("ROS 急停控制默认关闭；确认安全策略后设置 ROS_ENABLE_CONTROL=true")
        if not self._stop_client.wait_for_service(timeout_sec=1.0):
            raise RuntimeError("机器人停止服务不可用")
        future = self._stop_client.call_async(self._Trigger.Request())
        # 不使用 asyncio.to_thread，以兼容机器人 Humble 环境中的 Python 3.8。
        deadline = time.monotonic() + 3.0
        while not future.done() and time.monotonic() < deadline:
            await asyncio.sleep(0.02)
        if not future.done():
            raise TimeoutError("机器人停止服务超时")
        result = future.result()
        if not getattr(result, "success", False):
            raise RuntimeError(getattr(result, "message", "机器人拒绝停止请求"))


def create_telemetry_provider() -> MockTelemetryProvider | RosTelemetryProvider:
    mode = os.getenv("TELEMETRY_MODE", "mock").strip().lower()
    if mode == "mock":
        return MockTelemetryProvider()
    if mode == "ros":
        return RosTelemetryProvider()
    raise ValueError("TELEMETRY_MODE 仅支持 mock 或 ros")
