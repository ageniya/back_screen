"""systemd fail-stop helper: send zero to the gated chassis output only."""

import os
import time


def run():
    import rclpy
    from geometry_msgs.msg import Twist
    rclpy.init()
    node = rclpy.create_node("back_screen_motion_fail_stop")
    ns = "/" + (os.getenv("ROS_NAMESPACE") or os.getenv("ROBOT_NAME") or "zj_humanoid").strip("/")
    pub = node.create_publisher(Twist, ns + "/back_screen/motion/cmd_vel", 1)
    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline:
        pub.publish(Twist())
        rclpy.spin_once(node, timeout_sec=.05)
    node.destroy_node()
    rclpy.shutdown()


if __name__ == "__main__":
    run()
