#!/usr/bin/env bash
# 已部署后的手动一键启动。systemd enable 会在以后开机时自动执行。
set -euo pipefail
case "${1:-}" in
  pico) exec sudo systemctl start robot-back-screen-api.service robot-back-screen-kiosk.service ;;
  orin) exec sudo systemctl start robot-motion-supervisor.service ;;
  *) echo '用法：bash deploy/start.sh pico|orin' >&2; exit 2 ;;
esac
