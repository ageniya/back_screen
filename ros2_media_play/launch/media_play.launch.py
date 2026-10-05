from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument("display", default_value=":1"),
        DeclareLaunchArgument("xauthority", default_value="/run/user/1000/gdm/Xauthority"),
        DeclareLaunchArgument("media_dir", default_value="/opt/zj_humanoid/media_play"),
        Node(
            package="zj_media_play",
            executable="media_play_node",
            name="media_play",
            namespace="/zj_humanoid/robot/face_show",
            parameters=[{
                "display": LaunchConfiguration("display"),
                "xauthority": LaunchConfiguration("xauthority"),
                "media_dir": LaunchConfiguration("media_dir"),
            }],
            output="screen",
        ),
    ])
