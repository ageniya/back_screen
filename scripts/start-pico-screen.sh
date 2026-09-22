#!/usr/bin/env bash
# Pico 背屏启动脚本：在 Pico 桌面终端中执行即可重新打开全屏背屏。
set -euo pipefail

PREVIEW_DIR="/home/nav01/back-screen-preview"
PID_FILE="$PREVIEW_DIR/firefox.pid"
PROFILE_DIR="/home/nav01/.cache/back-screen-kiosk-profile"
PAGE_URL="http://127.0.0.1:5173/?api=http://127.0.0.1:8000/api/v1"

if [ -f "$PID_FILE" ]; then
  running_pid="$(sed -n '1p' "$PID_FILE")"
  if kill -0 "$running_pid" 2>/dev/null; then
    echo "背屏已经在显示中（进程 $running_pid）。"
    exit 0
  fi
fi

export DISPLAY=:1
export XAUTHORITY=/run/user/1000/gdm/Xauthority
export DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus

nohup /usr/lib/firefox/firefox \
  --no-remote \
  --profile "$PROFILE_DIR" \
  --kiosk "$PAGE_URL" \
  >"$PREVIEW_DIR/firefox.log" 2>&1 < /dev/null &

echo $! > "$PID_FILE"
echo "背屏正在启动。"
