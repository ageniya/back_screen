"""Launch the unified back-screen HTTP service through ROS2."""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description() -> LaunchDescription:
    return LaunchDescription([
        DeclareLaunchArgument("host", default_value="127.0.0.1"),
        DeclareLaunchArgument("port", default_value="8000"),
        Node(
            package="robot_back_screen",
            executable="robot-back-screen-api",
            name="robot_back_screen",
            output="screen",
            additional_env={
                "BACK_SCREEN_HOST": LaunchConfiguration("host"),
                "BACK_SCREEN_PORT": LaunchConfiguration("port"),
            },
        ),
    ])
