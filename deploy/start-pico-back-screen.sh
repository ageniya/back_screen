#!/usr/bin/env bash
# Pico 交付启动入口：启动背屏后端，确认健康后打开全屏页面。
# 需要先安装 robot-back-screen-api.service；视频服务为可选项。
set -euo pipefail

API_URL="${BACK_SCREEN_API_URL:-http://127.0.0.1:8000}"
PAGE_URL="${BACK_SCREEN_PAGE_URL:-${API_URL}/}"
PROFILE_DIR="${HOME}/.cache/robot-back-screen-kiosk"

if ! systemctl is-active --quiet robot-back-screen-api.service; then
  echo "正在启动背屏后端..."
  sudo systemctl start robot-back-screen-api.service
fi

for _ in $(seq 1 20); do
  if curl --silent --fail --max-time 1 "${API_URL}/healthz" >/dev/null; then
    break
  fi
  sleep 1
done

if ! curl --silent --fail --max-time 2 "${API_URL}/healthz" >/dev/null; then
  echo "背屏后端未通过健康检查：${API_URL}/healthz" >&2
  sudo systemctl --no-pager --full status robot-back-screen-api.service || true
  exit 1
fi

if systemctl list-unit-files zj-media-play.service >/dev/null 2>&1; then
  sudo systemctl start zj-media-play.service || {
    echo "提示：视频服务未能启动，背屏仍可使用。" >&2
  }
fi

export DISPLAY="${DISPLAY:-:1}"
export XAUTHORITY="${XAUTHORITY:-/run/user/1000/gdm/Xauthority}"
nohup firefox --no-remote --profile "${PROFILE_DIR}" --kiosk "${PAGE_URL}" \
  >"${HOME}/robot-back-screen-firefox.log" 2>&1 < /dev/null &

echo "背屏已启动：${PAGE_URL}"
