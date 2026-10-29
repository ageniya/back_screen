"""Robot-owned reset supervisor and final ROS chassis command gate.

Run on the chassis host. Chassis command subscriptions MUST be remapped to
the gated outputs; graph verification refuses reset when an input bypasses us.
No service call or reset occurs on startup. Only an operator request can reset.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import threading
import time
import socket

from robot_back_screen.services.chassis_reset import ChassisResetState
from robot_back_screen.services.motion_gate import MotionGate


def systemd_notify(message):
    address = os.getenv("NOTIFY_SOCKET")
    if not address:
        return
    if address.startswith("@"):
        address = "\0" + address[1:]
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as sock:
            sock.connect(address)
            sock.sendall(message.encode())
    except OSError:
        pass


def run():
    import rclpy
    from rclpy.node import Node
    from rclpy.executors import MultiThreadedExecutor
    from rclpy.callback_groups import ReentrantCallbackGroup
    from rclpy.qos import QoSProfile, DurabilityPolicy, ReliabilityPolicy, HistoryPolicy
    from geometry_msgs.msg import Twist
    from nav_msgs.msg import Odometry
    from chassis_msgs.msg import AGVNewState, SteerCommand
    from std_msgs.msg import String
    from std_srvs.srv import Trigger
    from action_msgs.msg import GoalStatusArray
    from action_msgs.srv import CancelGoal

    class Supervisor(Node):
        def __init__(self):
            super().__init__("back_screen_motion_supervisor")
            self.ns = "/" + (os.getenv("ROS_NAMESPACE") or os.getenv("ROBOT_NAME") or "zj_humanoid").strip("/")
            self.lock = threading.RLock()
            self.group = ReentrantCallbackGroup()
            self.machine = ChassisResetState(timeout_seconds=float(os.getenv("ROS_RESET_TIMEOUT_SECONDS", "10")))
            self.gate = MotionGate()
            self.active_goals = set()
            self.routing_ok = False
            self.routing_reason = "等待底盘运动出口检查"
            self.last_input_at = 0.0
            self.last_persisted = None
            self.record_path = Path(os.getenv("MOTION_TASK_RECORD", str(Path.home() / ".local/state/robot-back-screen/interrupted-tasks.json")))
            if self.record_path.exists():
                try:
                    old = json.loads(self.record_path.read_text())
                    self.gate.tasks = {t["id"]: t for t in old.get("tasks", [])[-100:] if isinstance(t, dict) and "id" in t}
                    self.gate.latch("主控重启：旧任务需重新确认")
                except (OSError, ValueError, TypeError) as exc:
                    self.get_logger().error("旧任务记录无法读取，保持运动锁定：" + str(exc))
            self.outputs = {}
            self.channels = {
                "cmd_vel/calib": (Twist, "back_screen/motion/cmd_vel"),
                "cmd_vel/manual": (Twist, "back_screen/motion/manual"),
                "chassis/steer_command": (SteerCommand, "back_screen/motion/steer"),
            }
            for source, (cls, output) in self.channels.items():
                self.outputs[source] = self.create_publisher(cls, self.ns + "/" + output, 1)
                self.create_subscription(cls, self.ns + "/" + source,
                    lambda msg, source=source: self.forward(source, msg), 1, callback_group=self.group)
            self.create_subscription(AGVNewState, self.ns + "/chassis/agv_state", self.chassis, 10, callback_group=self.group)
            self.create_subscription(Odometry, self.ns + "/chassis/odom_info", self.odom, 1, callback_group=self.group)
            # Action status contains goal IDs, so old tasks can be marked and
            # confirmed cancelled instead of merely hiding them on the screen.
            status_qos = QoSProfile(history=HistoryPolicy.KEEP_LAST, depth=1,
                reliability=ReliabilityPolicy.RELIABLE, durability=DurabilityPolicy.TRANSIENT_LOCAL)
            self.navigation = self.ns + "/navigation/navigation"
            self.create_subscription(GoalStatusArray, self.navigation + "/_action/status", self.goals, status_qos, callback_group=self.group)
            self.cancel = self.create_client(CancelGoal, self.navigation + "/_action/cancel_goal", callback_group=self.group)
            self.reset = self.create_client(Trigger, self.ns + "/chassis/agv_reset", callback_group=self.group)
            self.status_pub = self.create_publisher(String, self.ns + "/back_screen/reset_status", 1)
            self.create_service(Trigger, self.ns + "/back_screen/reset", self.reset_request, callback_group=self.group)
            # No start button: task software/operator must explicitly confirm a
            # NEW task. Reset success alone never opens the command gate.
            self.create_service(Trigger, self.ns + "/back_screen/confirm_new_task", self.confirm_task, callback_group=self.group)
            self.create_timer(.1, self.tick, callback_group=self.group)
            self.create_timer(.5, self.check_routes, callback_group=self.group)
            self.get_logger().info("复位主控已启动，运动门控锁定；不会自动调用复位或恢复任务")

        def zero(self):
            # Only use the calibrated-speed output for stop. Publishing zeros
            # on three competing command channels would alter steering angles.
            self.outputs["cmd_vel/calib"].publish(Twist())

        def forward(self, source, message):
            with self.lock:
                allowed = self.machine.state == "RESET_DONE" and self.machine.fresh() and self.routing_ok
                if not allowed:
                    self.gate.latch("等待复位或有效底盘反馈")
                if source == "chassis/steer_command":
                    values = [message.front_speed, message.front_angle, message.rear_speed, message.rear_angle]
                else:
                    values = [getattr(message.linear, x) for x in "xyz"] + [getattr(message.angular, x) for x in "xyz"]
                if self.gate.accept_velocity(values):
                    self.outputs[source].publish(message)
                    self.last_input_at = time.monotonic()

        def chassis(self, message):
            with self.lock:
                self.machine.update_chassis(bool(message.emergency), bool(message.collision), int(message.state), str(message.description))
                if self.machine.state != "RESET_DONE":
                    self.gate.latch("急停、未复位或复位中，旧任务需重新确认")
                    self.zero()

        def odom(self, message):
            with self.lock:
                twist = message.twist.twist
                self.machine.update_velocity([getattr(twist.linear, x) for x in "xyz"], [getattr(twist.angular, x) for x in "xyz"])

        def goals(self, message):
            with self.lock:
                statuses = [(bytes(s.goal_info.goal_id.uuid).hex(), int(s.status)) for s in message.status_list]
                self.active_goals = {goal for goal, status in statuses if status in (1, 2, 3)}
                self.gate.observe_goals(statuses)

        def check_routes(self):
            reason = None
            try:
                for source, (_, output) in self.channels.items():
                    original = self.get_subscriptions_info_by_topic(self.ns + "/" + source)
                    if any(e.node_name == "chassis_node" and e.node_namespace == self.ns for e in original):
                        reason = "底盘仍直接订阅 " + source + "，尚未经过运动门控"
                        break
                    final = self.get_subscriptions_info_by_topic(self.ns + "/" + output)
                    if not any(e.node_name == "chassis_node" and e.node_namespace == self.ns for e in final):
                        reason = "底盘未接入门控出口 " + output
                        break
                    pubs = self.get_publishers_info_by_topic(self.ns + "/" + output)
                    if any(e.node_name != self.get_name() or e.node_namespace != self.get_namespace() for e in pubs):
                        reason = "门控出口存在其它发布者，拒绝复位"
                        break
            except Exception as exc:
                reason = "运动链路检查失败：" + str(exc)
            with self.lock:
                self.routing_ok = reason is None
                self.routing_reason = reason
                if reason:
                    self.gate.latch(reason)

        def status(self):
            enabled = os.getenv("ROS_ENABLE_RESET", "false").lower() == "true"
            ready = self.routing_ok and self.cancel.service_is_ready()
            result = self.machine.view(ready, enabled, self.reset.service_is_ready())
            if not self.routing_ok:
                result["blockReason"] = self.routing_reason
                result["blockReasons"] = [self.routing_reason] + result["blockReasons"]
            result["motionGate"] = self.gate.status()
            result["owner"] = "back_screen_motion_supervisor"
            return result

        def tick(self):
            with self.lock:
                self.machine.tick()
                if self.machine.state != "RESET_DONE" or not self.machine.fresh() or not self.routing_ok:
                    self.gate.latch(self.machine.error or "等待人工复位")
                # A command-source stall must never hold its last nonzero speed.
                if self.gate.locked or time.monotonic() - self.last_input_at > .5:
                    self.zero()
                self.status_pub.publish(String(data=json.dumps(self.status(), ensure_ascii=False)))
                # Persist task interruption state; high-rate drop counters are
                # telemetry only, not a reason to write disk at 10 Hz.
                state_record = json.dumps({"tasks": list(self.gate.tasks.values()), "needsConfirmation": self.gate.needs_confirmation}, ensure_ascii=False)
                if state_record != self.last_persisted:
                    try:
                        self.record_path.parent.mkdir(parents=True, exist_ok=True)
                        temp = self.record_path.with_suffix(".tmp")
                        temp.write_text(state_record)
                        temp.replace(self.record_path)
                        self.last_persisted = state_record
                    except OSError as exc:
                        self.gate.latch("任务中断记录写入失败")
                        self.get_logger().error(str(exc))
                systemd_notify("WATCHDOG=1")

        def reset_request(self, request, response):
            with self.lock:
                view = self.status()
                if not view["resetAllowed"]:
                    response.success = False
                    response.message = view["blockReason"]
                    return response
                token = self.machine.begin()
                self.gate.latch("复位请求：清空速度目标，中断旧任务，需重新确认")
                self.zero()
                try:
                    # The interrupted-task record is durable before sending
                    # the reset, not a future UI refresh side effect.
                    self.record_path.parent.mkdir(parents=True, exist_ok=True)
                    temp = self.record_path.with_suffix(".tmp")
                    temp.write_text(json.dumps({"tasks": list(self.gate.tasks.values()), "needsConfirmation": True}, ensure_ascii=False))
                    temp.replace(self.record_path)
                except OSError as exc:
                    self.machine.fail("任务中断记录写入失败", lock=True)
                    response.success = False
                    response.message = str(exc)
                    return response
            threading.Thread(target=self.perform_reset, args=(token,), daemon=True).start()
            response.success = True
            response.message = "复位请求已受理；运动已锁定，等待任务取消和底盘反馈"
            return response

        @staticmethod
        def wait_future(future, timeout):
            done = threading.Event()
            future.add_done_callback(lambda _: done.set())
            if not done.wait(timeout):
                raise TimeoutError("主控服务响应超时")
            return future.result()

        def perform_reset(self, token):
            try:
                # Zero GoalInfo cancels ALL navigation goals, including queued
                # ones known by the navigation action server.
                result = self.wait_future(self.cancel.call_async(CancelGoal.Request()), 2)
                if result.return_code != 0:
                    raise RuntimeError("导航任务取消失败，保持运动锁定")
                deadline = time.monotonic() + 2
                while True:
                    with self.lock:
                        self.machine.ensure_pending(token)
                        if not self.active_goals:
                            break
                    if time.monotonic() >= deadline:
                        raise RuntimeError("旧任务尚未结束，未发送底盘复位")
                    time.sleep(.02)
                with self.lock:
                    if not self.routing_ok:
                        raise RuntimeError("运动链路已变化，未发送底盘复位")
                    if self.active_goals:
                        raise RuntimeError("复位前出现新的运行任务，保持锁定")
                    self.zero()
                    self.machine.mark_sent(token, require_ack=True)
                    future = self.reset.call_async(Trigger.Request())
                result = self.wait_future(future, 3)
                if not result.success:
                    raise RuntimeError(result.message or "底盘拒绝复位")
                with self.lock:
                    self.machine.accept_response(token)
            except Exception as exc:
                with self.lock:
                    if self.machine.request_id == token:
                        self.machine.fail(str(exc), lock=not self.machine.fresh())
                        self.machine.fault_locked = False
                    self.gate.latch(str(exc))
                    self.zero()

        def confirm_task(self, request, response):
            # This is a separate manual/task-system confirmation, not invoked
            # by the reset handler and not an automatic retry of the old goal.
            with self.lock:
                try:
                    if not self.routing_ok or not self.machine.fresh() or self.machine.emergency is not False:
                        raise RuntimeError("底盘状态或运动链路不可用")
                    if not self.cancel.service_is_ready():
                        raise RuntimeError("导航任务管理不可用")
                    if self.machine.speed_at is None or time.monotonic() - self.machine.speed_at > self.machine.stale_seconds:
                        raise RuntimeError("速度反馈过期，无法确认静止")
                    self.gate.confirm_new_task(self.machine.state == "RESET_DONE", self.machine.stationary, self.active_goals)
                    response.success = True
                    response.message = "已确认新任务；请重新下发任务，旧任务不会重放"
                except RuntimeError as exc:
                    response.success = False
                    response.message = str(exc)
                return response

    rclpy.init()
    node = Supervisor()
    executor = MultiThreadedExecutor(num_threads=4)
    executor.add_node(node)
    systemd_notify("READY=1")
    try:
        executor.spin()
    finally:
        with node.lock:
            node.gate.latch("主控退出")
            # SIGINT 可先关闭 rclpy context；此时发布会抛异常。
            # ExecStopPost 仍会用独立节点发送零速度。
            if rclpy.ok():
                node.zero()
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    run()
