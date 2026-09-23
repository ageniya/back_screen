#!/usr/bin/env bash
# Pico 登录桌面后执行：使用同一个 8000 服务全屏显示背屏。
set -euo pipefail

PROFILE_DIR="${HOME}/.cache/robot-back-screen-kiosk"
PAGE_URL="http://127.0.0.1:8000/"

nohup firefox --no-remote --profile "$PROFILE_DIR" --kiosk "$PAGE_URL" \
  >"${HOME}/robot-back-screen-firefox.log" 2>&1 < /dev/null &

echo "背屏正在启动：${PAGE_URL}"
