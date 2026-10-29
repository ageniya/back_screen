#!/usr/bin/env bash
# Pico 屏幕入口。前台运行，供 systemd 监督；也可由 nav01 手动执行。
set -euo pipefail
export DISPLAY="${DISPLAY:-:1}"
export XAUTHORITY="${XAUTHORITY:-/run/user/1000/gdm/Xauthority}"
page_url="${BACK_SCREEN_PAGE_URL:-http://127.0.0.1:8000/}"
profile_dir="${FIREFOX_PROFILE_DIR:-${HOME}/.cache/robot-back-screen-kiosk}"
for _ in {1..60}; do
  if curl -fsS --max-time 1 http://127.0.0.1:8000/healthz >/dev/null 2>&1 \
    && [[ -S "/tmp/.X11-unix/X${DISPLAY#:}" ]]; then
    exec /usr/lib/firefox/firefox --no-remote --profile "$profile_dir" --kiosk "$page_url"
  fi
  sleep 1
done
echo '背屏 API 或桌面未就绪，请检查服务日志' >&2
exit 1
