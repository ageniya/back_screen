#!/usr/bin/env bash
# 在 ROS2 工作空间的 src/robot_back_screen 目录执行：构建前端，再由 colcon 打包。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT/frontend"
npm ci
npm run build

cd "$(dirname "$ROOT")"
colcon build --packages-select robot_back_screen
