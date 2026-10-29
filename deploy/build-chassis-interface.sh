#!/usr/bin/env bash
# Pico 缺少 chassis_msgs 时，将与 Orin 同版的消息接口构建到背屏私有目录。
set -eo pipefail
source /etc/nav01/Middleware.env
source /opt/ros/humble/setup.bash
if python3 -c 'from chassis_msgs.msg import AGVNewState' 2>/dev/null; then
  echo '当前 ROS 环境已包含 AGVNewState，无需构建。'
  exit 0
fi
task_deploy_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
task_install_dir="${1:?请指定背屏私有接口构建目录}"
mkdir -p "$task_install_dir"
cd "$task_install_dir"
colcon build --base-paths "$task_deploy_dir/ros_interfaces" --packages-select chassis_msgs \
  --cmake-args -DPYTHON_EXECUTABLE=/usr/bin/python3 -DPython3_EXECUTABLE=/usr/bin/python3 \
  -DBUILD_TESTING=OFF
echo "构建完成。背屏启动前加载：source $task_install_dir/install/setup.bash"
