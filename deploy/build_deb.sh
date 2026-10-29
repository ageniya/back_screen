#!/usr/bin/env bash
# 在 ROS2 工作空间的 src/robot_back_screen 目录执行：构建前端及 ROS 安装树。
# 本脚本不会制作 .deb；由中间件发布流程再对 install/ 打包。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT/frontend"
npm ci
npm run build

cd "$(dirname "$ROOT")"
colcon build --packages-select robot_back_screen
echo 'ROS 安装树已构建；.deb 请交由中间件发布流程生成。'
