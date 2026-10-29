#!/usr/bin/env bash
# Install on the Orin chassis host only. Never sends reset or nonzero motion.
set -eo pipefail
[[ "$EUID" -eq 0 ]] || { echo "请以 root 安装运动门控服务" >&2; exit 1; }
task_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if systemctl is-active --quiet zj-humanoid-chassis.service; then
  task_chassis_service=zj-humanoid-chassis.service
elif systemctl is-active --quiet zj-humanoid-orin-chassis-supervisor.service; then
  task_chassis_service=zj-humanoid-orin-chassis-supervisor.service
else
  echo "未找到正在运行的底盘服务，停止安装" >&2
  exit 1
fi
source /etc/naviai/Middleware.env
export ROBOT_NAME="${ROBOT_NAME:-zj_humanoid}"
export ROS_NAMESPACE="$ROBOT_NAME"
# Require measured standstill before restarting the chassis ROS wrapper.
/usr/bin/python3 - <<'PY'
import os, time, math
import rclpy
from nav_msgs.msg import Odometry
rclpy.init(); node = rclpy.create_node('back_screen_install_standstill_check')
ns='/' + os.environ['ROBOT_NAME'].strip('/')
state={'count':0}
def check(m):
    t=m.twist.twist
    values=[getattr(t.linear,a) for a in 'xyz']+[getattr(t.angular,a) for a in 'xyz']
    state['count'] = state['count']+1 if all(math.isfinite(v) and abs(v)<=1e-4 for v in values) else 0
sub=node.create_subscription(Odometry,ns+'/chassis/odom_info',check,1)
end=time.monotonic()+5
while time.monotonic()<end and state['count']<3:rclpy.spin_once(node,timeout_sec=.1)
node.destroy_node();rclpy.shutdown()
if state['count']<3:raise SystemExit('未确认底盘连续静止，停止安装')
print('已确认底盘连续静止')
PY
task_backup="/var/backups/robot-back-screen-motion/$(date +%Y%m%d-%H%M%S)"
install -d -m 0755 "$task_backup" /opt/robot-back-screen-control/deploy /etc/robot-back-screen-motion
cp -a /opt/ros/humble/share/chassis/launch/chassis.launch.py "$task_backup/chassis.launch.py"
if [[ -d /opt/robot-back-screen-control/robot_back_screen ]]; then
  cp -a /opt/robot-back-screen-control/robot_back_screen "$task_backup/robot_back_screen"
fi
# Orin 只运行复位主控，删除先前复制到这里的 API、网页和数据适配源码。
/usr/bin/python3 - <<'PY'
from pathlib import Path
import shutil
p=Path('/opt/robot-back-screen-control/robot_back_screen')
if p.is_dir(): shutil.rmtree(p)
PY
install -d -m 0755 /opt/robot-back-screen-control/robot_back_screen/services
for task_name in __init__.py motion_supervisor.py motion_supervisor_stop.py; do
  install -m 0644 "$task_root/robot_back_screen/$task_name" /opt/robot-back-screen-control/robot_back_screen/
done
for task_name in __init__.py chassis_reset.py motion_gate.py; do
  install -m 0644 "$task_root/robot_back_screen/services/$task_name" /opt/robot-back-screen-control/robot_back_screen/services/
done
install -m 0755 "$task_root/deploy/start-motion-supervisor.sh" /opt/robot-back-screen-control/deploy/
install -m 0644 "$task_root/deploy/robot-motion-supervisor.service" /etc/systemd/system/
cat > /etc/robot-back-screen-motion/env <<EOF
ROBOT_NAME=$ROBOT_NAME
ROS_ENABLE_RESET=true
ROS_RESET_TIMEOUT_SECONDS=10
MOTION_TASK_RECORD=/home/naviai/.local/state/robot-back-screen/interrupted-tasks.json
EOF
/usr/bin/python3 - <<'PY'
from pathlib import Path
p=Path('/opt/ros/humble/share/chassis/launch/chassis.launch.py')
s=p.read_text()
if 'back_screen/motion/cmd_vel' not in s:
    marker='        output="log",'
    if s.count(marker)!=1:raise SystemExit('底盘 launch 结构与预期不符，停止修改')
    s=s.replace(marker, marker+'''
        # Back-screen reset supervisor is the sole chassis motion gateway.
        remappings=[
            ("cmd_vel/calib", "back_screen/motion/cmd_vel"),
            ("cmd_vel/manual", "back_screen/motion/manual"),
            ("chassis/steer_command", "back_screen/motion/steer"),
        ],''')
    compile(s,str(p),'exec')
    p.write_text(s)
PY
systemctl daemon-reload
systemctl restart "$task_chassis_service"
systemctl enable robot-motion-supervisor.service
systemctl restart robot-motion-supervisor.service
echo "运动门控已安装并锁定；未执行复位或任务确认。备份：$task_backup"
