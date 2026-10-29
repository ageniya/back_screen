#!/usr/bin/env bash
# Pico API 前台入口，供 systemd 托管。
set -euo pipefail
source /etc/nav01/Middleware.env
source /opt/ros/humble/setup.bash
if ! /usr/bin/python3 -c 'from chassis_msgs.msg import AGVNewState' 2>/dev/null; then
  source /opt/robot-back-screen/ros_interfaces/install/setup.bash
fi
export PYTHONPATH="/opt/robot-back-screen:${PYTHONPATH:-}"
exec /opt/robot-back-screen/.venv/bin/uvicorn robot_back_screen.main:app \
  --host "${BACK_SCREEN_HOST:-127.0.0.1}" --port "${BACK_SCREEN_PORT:-8000}"
