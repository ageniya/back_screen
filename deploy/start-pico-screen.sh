#!/usr/bin/env bash
# Pico 屏幕入口。前台运行，供 systemd 监督；也可由 nav01 手动执行。
set -euo pipefail
export DISPLAY="${DISPLAY:-:1}"
export XAUTHORITY="${XAUTHORITY:-/run/user/1000/gdm/Xauthority}"
page_url="${BACK_SCREEN_PAGE_URL:-http://127.0.0.1:8000/}"
profile_dir="${FIREFOX_PROFILE_DIR:-${HOME}/.cache/robot-back-screen-kiosk}"
export DBUS_SESSION_BUS_ADDRESS="${DBUS_SESSION_BUS_ADDRESS:-unix:path=/run/user/$(id -u)/bus}"
for _ in {1..60}; do
  if curl -fsS --max-time 1 http://127.0.0.1:8000/healthz >/dev/null 2>&1 \
    && [[ -S "/tmp/.X11-unix/X${DISPLAY#:}" ]]; then
    # 用户会话启动后关闭 GNOME 锁屏/空闲休眠及 X11 屏保；保持背屏可操作。
    if command -v gsettings >/dev/null 2>&1; then
      gsettings set org.gnome.desktop.screensaver lock-enabled false 2>/dev/null || true
      gsettings set org.gnome.desktop.session idle-delay 'uint32 0' 2>/dev/null || true
    fi
    if command -v xset >/dev/null 2>&1; then
      xset s off 2>/dev/null || true
      xset s noblank 2>/dev/null || true
      xset -dpms 2>/dev/null || true
    fi
    exec /usr/lib/firefox/firefox --no-remote --profile "$profile_dir" --kiosk "$page_url"
  fi
  sleep 1
done
echo '背屏 API 或桌面未就绪，请检查服务日志' >&2
exit 1
