#!/usr/bin/env bash
set -eo pipefail
task_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
task_robot_name="${ROBOT_NAME:-zj_humanoid}"
task_reset_enabled="${ROS_ENABLE_RESET:-false}"
source /etc/naviai/Middleware.env
export ROBOT_NAME="$task_robot_name" ROS_NAMESPACE="$task_robot_name"
export ROS_ENABLE_RESET="$task_reset_enabled"
export PYTHONPATH="$task_root:${PYTHONPATH:-}"
cd "$task_root"
if [[ "${1:-}" == stop ]]; then
  exec /usr/bin/python3 -m robot_back_screen.motion_supervisor_stop
fi
exec /usr/bin/python3 -m robot_back_screen.motion_supervisor
