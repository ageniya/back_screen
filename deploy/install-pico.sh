#!/usr/bin/env bash
# 在 Pico 上从已构建的仓库安装 API、网页和开机显示服务。
set -euo pipefail
[[ "$EUID" -eq 0 ]] || { echo '请使用 sudo 运行' >&2; exit 1; }
task_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
task_target=/opt/robot-back-screen
task_web="$task_root/frontend/dist"
[[ -f "$task_web/index.html" && -f "$task_web/runtime-config.js" && -d "$task_web/models" ]] || {
  echo '缺少完整的 frontend/dist；先在开发电脑执行 npm ci && npm run build，再复制整个仓库到 Pico。' >&2
  exit 1
}
getent passwd nav01 >/dev/null || { echo 'Pico 缺少 nav01 用户' >&2; exit 1; }
command -v /usr/bin/python3 >/dev/null || exit 1

task_backup="/var/backups/robot-back-screen/$(date +%Y%m%d-%H%M%S)"
install -d -m 0755 "$task_target/deploy" /etc/robot-back-screen "$task_backup"
for task_file in /etc/systemd/system/robot-back-screen-api.service \
                 /etc/systemd/system/robot-back-screen-kiosk.service \
                 /etc/robot-back-screen/env \
                 /etc/gdm3/custom.conf; do
  if [[ -f "$task_file" ]]; then cp -a "$task_file" "$task_backup/$(basename "$task_file")"; fi
done
if [[ -d "$task_target/robot_back_screen" ]]; then
  cp -a "$task_target/robot_back_screen" "$task_backup/robot_back_screen"
fi
if [[ -d "$task_target/frontend/dist" ]]; then
  cp -a "$task_target/frontend/dist" "$task_backup/web"
fi

# 只复制 Pico 运行所需的文件，不把源码文档、测试或视频包放到运行目录。
/usr/bin/python3 - <<'PY'
from pathlib import Path
import shutil
root=Path('/opt/robot-back-screen')
for path in (root/'robot_back_screen', root/'frontend/dist'):
    if path.is_dir(): shutil.rmtree(path)
PY
cp -a "$task_root/robot_back_screen" "$task_target/"
install -d -m 0755 "$task_target/frontend"
cp -a "$task_web" "$task_target/frontend/"
install -m 0644 "$task_root/requirements.txt" "$task_target/requirements.txt"
for task_name in start-pico-api.sh start-pico-screen.sh build-chassis-interface.sh; do
  install -m 0755 "$task_root/deploy/$task_name" "$task_target/deploy/$task_name"
done
cp -a "$task_root/deploy/ros_interfaces" "$task_target/deploy/"

if [[ ! -x "$task_target/.venv/bin/uvicorn" ]]; then
  /usr/bin/python3 -m venv --system-site-packages "$task_target/.venv"
fi
"$task_target/.venv/bin/python" -m pip install -r "$task_target/requirements.txt"
chown -R nav01:nav01 "$task_target"

source /etc/nav01/Middleware.env
source /opt/ros/humble/setup.bash
if ! /usr/bin/python3 -c 'from chassis_msgs.msg import AGVNewState' 2>/dev/null; then
  sudo -u nav01 bash "$task_target/deploy/build-chassis-interface.sh" "$task_target/ros_interfaces"
fi

if [[ ! -f /etc/robot-back-screen/env ]]; then
  cat > /etc/robot-back-screen/env <<'EOF'
TELEMETRY_MODE=ros
ROBOT_MODEL=WA-T
ROBOT_NAME=zj_humanoid
LOCAL_RESOURCE_SOURCE=pico
BACK_SCREEN_DEVICE_ROLE=pico
ORIN_IP=192.168.217.100
BACK_SCREEN_WEB_DIR=/opt/robot-back-screen/frontend/dist
ROS_ENABLE_CONTROL=false
ROS_ENABLE_RESET=true
ROS_BATTERY_TOPICS=/web/battery_info
ROS_ODOM_TOPICS=/zj_humanoid/chassis/odom_info
ROS_CHASSIS_STATE_TOPICS=/zj_humanoid/chassis/agv_state
ROS_LIDAR_1_TOPIC=/zj_humanoid/chassis/laser_scan
ROS_JOINT_STATES_TOPIC=/zj_humanoid/upperlimb/joint_states
ROS_LEFT_TCP_TOPIC=/zj_humanoid/upperlimb/tcp_pose/left_arm
ROS_RIGHT_TCP_TOPIC=/zj_humanoid/upperlimb/tcp_pose/right_arm
ROS_UPPERLIMB_STATE_TOPIC=/zj_humanoid/upperlimb/uplimb_state
ROS_DEPTH_CAMERA_TOPIC=/zj_humanoid/sensor/realsense_head/depth/image_rect_raw
ROS_CAMERA_TOPIC=/zj_humanoid/sensor/realsense_head/color/image_raw
ALARM_CPU_WARN_PERCENT=95
ALARM_PERSIST_SECONDS=5
EOF
fi

install -m 0644 "$task_root/deploy/robot-back-screen-api.service" /etc/systemd/system/
install -m 0644 "$task_root/deploy/robot-back-screen-kiosk.service" /etc/systemd/system/
# Pico 开机自动登录 nav01，桌面起来后由 kiosk.service 打开背屏。
# 只修改已有 GDM 配置；安装前的文件已备份到 task_backup。
if [[ -f /etc/gdm3/custom.conf ]]; then
  /usr/bin/python3 - <<'PY'
from pathlib import Path
import re
path = Path('/etc/gdm3/custom.conf')
lines = path.read_text().splitlines(keepends=True)
result = []
in_daemon = False
found_daemon = False
for line in lines:
    section = re.match(r'^\s*\[([^]]+)\]', line)
    if section:
        in_daemon = section.group(1).lower() == 'daemon'
        result.append(line)
        if in_daemon:
            found_daemon = True
            result.extend(('AutomaticLoginEnable=true\n', 'AutomaticLogin=nav01\n'))
        continue
    if in_daemon and re.match(r'^\s*(AutomaticLoginEnable|AutomaticLogin)\s*=', line):
        continue
    result.append(line)
if not found_daemon:
    result.extend(('\n[daemon]\n', 'AutomaticLoginEnable=true\n', 'AutomaticLogin=nav01\n'))
path.write_text(''.join(result))
PY
fi
systemctl daemon-reload
systemctl enable robot-back-screen-api.service robot-back-screen-kiosk.service
# 停止旧预览实例，否则它会继续占用 8000 端口或盖住新页面。
if systemctl cat zj-humanoid-back-screen.service >/dev/null 2>&1; then
  systemctl disable --now zj-humanoid-back-screen.service
fi
/usr/bin/python3 - <<'PY'
from pathlib import Path
import os, signal
base=Path('/home/nav01/back-screen-preview')
for name, marker in [('server.pid','robot_back_screen.main:app'),
                     ('web-server.pid','http.server 5173'),
                     ('firefox.pid','back-screen-kiosk-profile')]:
    file=base/name
    if not file.is_file(): continue
    try:
        pid=int(file.read_text().strip())
        if marker in Path('/proc/%d/cmdline'%pid).read_bytes().replace(b'\0',b' ').decode(errors='replace'):
            os.kill(pid,signal.SIGTERM)
            file.unlink()
    except (ValueError,FileNotFoundError,ProcessLookupError,PermissionError): pass
PY
systemctl restart robot-back-screen-api.service
for _ in {1..30}; do
  if curl -fsS --max-time 1 http://127.0.0.1:8000/healthz >/dev/null; then break; fi
  sleep 1
done
curl -fsS --max-time 2 http://127.0.0.1:8000/healthz >/dev/null || {
  echo 'API 未启动；查看 journalctl -u robot-back-screen-api.service' >&2; exit 1;
}
systemctl restart robot-back-screen-kiosk.service
echo "Pico 安装完成。网页：http://127.0.0.1:8000/，开机自启已启用。备份：$task_backup"
