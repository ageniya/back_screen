"""Manual ROS integration test: fixed isolated domain + namespace, no hardware.

Run after loading Humble on a development host with chassis_msgs installed.
This program never subscribes to or calls zj_humanoid robot interfaces.
"""

import os
import subprocess
import sys
import threading
import time
import json
from pathlib import Path


def main():
    os.environ["ROS_DOMAIN_ID"] = "173"
    os.environ["ROS_LOCALHOST_ONLY"] = "1"
    os.environ.pop("CYCLONEDDS_URI", None)
    os.environ["ROBOT_NAME"] = "back_screen_reset_test"
    os.environ["ROS_NAMESPACE"] = "back_screen_reset_test"
    os.environ["ROS_ENABLE_CONTROL"] = "true"
    os.environ["ROS_ENABLE_RESET"] = "true"
    os.environ["ROS_RESET_TIMEOUT_SECONDS"] = "4"
    os.environ["MOTION_TASK_RECORD"] = "/tmp/backscreen-test-interrupted-tasks.json"
    import rclpy
    from rclpy.node import Node
    from rclpy.executors import MultiThreadedExecutor
    from rclpy.callback_groups import ReentrantCallbackGroup
    from rclpy.qos import QoSProfile, DurabilityPolicy
    from geometry_msgs.msg import Twist
    from nav_msgs.msg import Odometry
    from chassis_msgs.msg import AGVNewState, SteerCommand
    from action_msgs.msg import GoalStatusArray
    from action_msgs.srv import CancelGoal
    from std_msgs.msg import String
    from std_srvs.srv import Trigger
    rclpy.init()
    ns = "/back_screen_reset_test"
    node = Node("chassis_node", namespace=ns)
    group = ReentrantCallbackGroup()
    state = {"emergency": False, "drop": False, "nonzero": 0, "resets": 0,
             "cancelFail": False, "hold": False, "readyAt": 0, "events": [], "status": {}}
    pubs = {
        "chassis": node.create_publisher(AGVNewState, ns + "/chassis/agv_state", 10),
        "odom": node.create_publisher(Odometry, ns + "/chassis/odom_info", 10),
        "input": node.create_publisher(Twist, ns + "/cmd_vel/calib", 1),
        "goals": node.create_publisher(GoalStatusArray, ns + "/navigation/navigation/_action/status",
                    QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL)),
    }
    def receive(m):
        if abs(m.linear.x) > 1e-5:
            state["nonzero"] += 1
    node.create_subscription(Twist, ns + "/back_screen/motion/cmd_vel", receive, 1)
    node.create_subscription(Twist, ns + "/back_screen/motion/manual", lambda m: None, 1)
    node.create_subscription(SteerCommand, ns + "/back_screen/motion/steer", lambda m: None, 1)
    def status(m):
        state["status"] = json.loads(m.data)
    node.create_subscription(String, ns + "/back_screen/reset_status", status, 10)
    def feedback():
        if state["drop"]:
            return
        m = AGVNewState()
        m.emergency = state["emergency"]
        m.collision = True  # Deliberately not an added FR-02 reset condition.
        done = state["readyAt"] and time.monotonic() >= state["readyAt"] and not state["hold"]
        m.state = 1 if done else 4
        m.description = "空闲中" if done else "等待复位"
        m.battery_voltage = 48.0
        pubs["chassis"].publish(m)
        pubs["odom"].publish(Odometry())
        pubs["goals"].publish(GoalStatusArray())
    node.create_timer(.05, feedback, callback_group=group)
    def cancel(req, response):
        state["events"].append("cancel")
        response.return_code = 1 if state["cancelFail"] else 0
        return response
    def reset(req, response):
        state["events"].append("reset")
        state["resets"] += 1
        state["readyAt"] = time.monotonic() + .4
        response.success = True
        return response
    node.create_service(CancelGoal, ns + "/navigation/navigation/_action/cancel_goal", cancel, callback_group=group)
    node.create_service(Trigger, ns + "/chassis/agv_reset", reset, callback_group=group)
    reset_client = node.create_client(Trigger, ns + "/back_screen/reset")
    confirm_client = node.create_client(Trigger, ns + "/back_screen/confirm_new_task")
    executor = MultiThreadedExecutor(num_threads=3)
    executor.add_node(node)
    thread = threading.Thread(target=executor.spin, daemon=True)
    thread.start()
    log = open("/tmp/backscreen-reset-integration.log", "w")
    process = subprocess.Popen([sys.executable, "-m", "robot_back_screen.motion_supervisor"], env=os.environ.copy(), stdout=log, stderr=log)
    def until(predicate, label, timeout=8):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                print("PASS:", label, flush=True)
                return
            if process.poll() is not None:
                raise RuntimeError("监督模块提前退出：" + Path(log.name).read_text())
            time.sleep(.05)
        raise AssertionError(label + ": " + json.dumps(state["status"], ensure_ascii=False))
    def call(client):
        assert client.wait_for_service(timeout_sec=5)
        future = client.call_async(Trigger.Request())
        until(future.done, "service response", 5)
        return future.result()
    def motion():
        m = Twist(); m.linear.x = .2
        for _ in range(8):
            pubs["input"].publish(m); time.sleep(.03)
    try:
        until(lambda: state["status"].get("resetAllowed"), "released + routes verified")
        motion()
        assert state["nonzero"] == 0, "启动时不得放行运动"
        assert call(reset_client).success
        assert not call(reset_client).success, "禁止重复复位"
        until(lambda: state["status"].get("state") == "RESET_DONE", "real feedback needed for completion")
        assert state["resets"] == 1
        assert state["events"][:2] == ["cancel", "reset"]
        motion()
        assert state["nonzero"] == 0, "复位完成不得自动恢复旧运动"
        assert call(confirm_client).success
        motion()
        until(lambda: state["nonzero"] > 0, "explicit NEW task confirmation opens gate")
        state["emergency"] = True
        until(lambda: state["status"].get("state") == "E_STOP_ACTIVE", "physical estop closes gate")
        before = state["nonzero"]; motion()
        assert state["nonzero"] == before
        state["emergency"] = False
        until(lambda: state["status"].get("resetAllowed"), "physical release waits for manual reset")
        state["hold"] = True
        assert call(reset_client).success
        until(lambda: "超时" in (state["status"].get("error") or ""), "timeout stays locked", 8)
        assert state["status"]["motionGate"]["locked"]
        assert call(reset_client).success
        state["drop"] = True
        until(lambda: state["status"].get("state") == "E_STOP_ACTIVE", "communication loss never completes reset", 8)
        assert state["status"]["motionGate"]["locked"]
        print("ALL ISOLATED ROS TESTS PASSED", flush=True)
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill(); process.wait()
        executor.shutdown()
        node.destroy_node(); rclpy.shutdown(); log.close()


if __name__ == "__main__":
    main()
