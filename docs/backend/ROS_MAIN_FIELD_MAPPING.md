# 背屏每项数据与 ROS2 topic 对照

更新日期：2026-11-11。以下按当前 `telemetry.py`、`unified_service.py` 和前端代码整理，表示已写入的接入方式，不代表此刻机器人上的话题都有输出。启动与页面操作见 [使用说明](../背屏交付与使用手册.md)。

## 1. 命名空间和数据所在设备

下表使用 `/zj_humanoid` 举例。后端优先使用 `ROS_NAMESPACE`，其次使用 `ROBOT_NAME`，两者都为空才使用 `zj_humanoid`。Orin 主控与 Pico 后端必须使用相同的实际前缀。

“设备”指通常负责发布数据的计算机。Pico 和 Orin 位于同一 ROS2 网络时，在任一端都可能看到另一端的话题；能在 Pico 看到话题不等于发布节点运行在 Pico。

安装脚本为上肢、相机等接口写入显式配置。旧配置会被保留，更新后请核对 Pico `/etc/robot-back-screen/env` 中的话题名。`ROS_BATTERY_TOPICS`、`ROS_BATTERY2_TOPICS`、`ROS_ODOM_TOPICS`、`ROS_CHASSIS_STATE_TOPICS` 是额外订阅列表，逗号分隔；上肢和相机等单话题变量直接指定其接口。

## 2. 运动、关节和手部

| 页面数据 | 发布设备 / topic | 消息类型 | 实际读取或计算 |
| --- | --- | --- | --- |
| 当前位置 XYZ | Orin：`/zj_humanoid/chassis/odom_info`；同时兼容 `/chassis/odom_info` | `nav_msgs/msg/Odometry` | `pose.pose.position.x/y/z`；相对于消息的 `header.frame_id` 坐标系，不是背屏自行设置的初始点 |
| 当前速度 | 同上 | `nav_msgs/msg/Odometry` | `sqrt(vx² + vy² + vz²)`，单位 m/s；角速度另外用于确认复位前静止 |
| 关节数值 | Pico：`/zj_humanoid/upperlimb/joint_states` | `sensor_msgs/msg/JointState` | 按 `name` 对应 `position`；状态页摘要显示前 6 项并将弧度转为度 |
| 3D 姿态 | 同上 | `sensor_msgs/msg/JointState` | `name → position` 驱动 URDF；转动关节用 rad，升降等直线关节用 m |
| 左手 TCP | Pico：`/zj_humanoid/upperlimb/tcp_pose/left_arm` | `upperlimb_msgs/msg/Pose` | 提取 XYZ；原坐标系由上肢发布端定义，背屏不做坐标变换 |
| 右手 TCP | Pico：`/zj_humanoid/upperlimb/tcp_pose/right_arm` | `upperlimb_msgs/msg/Pose` | 同上 |
| 上肢指令与运行状态 | Pico：`/zj_humanoid/upperlimb/uplimb_state` | `upperlimb_msgs/msg/UplimbState` | `cmd_num`、`cmd_name`、左右奇异位和 `iddp_status`，保存到 `upperLimbState` |
| 左右手指关节 | Pico：`/zj_humanoid/hand/joint_states` | `sensor_msgs/msg/JointState` | `position`、`effort` 按关节名 `_LEFT` / `_RIGHT` 分组；保存于 `hands`，不覆盖上肢关节 |
| 左腕六维力 | Pico：`/zj_humanoid/hand/wrist_force_sensor/left` | `geometry_msgs/msg/WrenchStamped` | `wrench.force` 和 `wrench.torque`，保存于 `wristForces.left` |
| 右腕六维力 | Pico：`/zj_humanoid/hand/wrist_force_sensor/right` | `geometry_msgs/msg/WrenchStamped` | 同上，保存于 `wristForces.right` |
| 左/右腕合力 | 同上两条腕力 topic | 前端计算 | 分别计算 `sqrt(Fx² + Fy² + Fz²)`，单位 N；这是腕部受力，不是夹爪夹持力 |
| 页面“模式” | `/zj_humanoid/robot/robot_state` | `navi_robot_msgs/msg/RobotState`，缺少该包时兼容 `robot_msgs/msg/RobotState` | 由 `state` 转为运行、停止等文字；它并不等同于自动/手动模式。配置了 `ROS_WORK_STATUS_TOPIC` 且有对应 `WorkStatus` 类型时，也可读取其 `mode` |
| 关节温度诊断字段 | `/zj_humanoid/robot/joint_motor/temperatures` | `sensor_msgs/msg/JointState` | `effort` 中的有效温度取最大值，存于 `diagnosticMetrics.maxJointTemperature`；不是首页两台计算单元的温度 |
| 关节错误诊断字段 | `/zj_humanoid/robot/joint_motor/errors` | `sensor_msgs/msg/JointState` | 保存 `effort` 到 `diagnosticMetrics.jointErrorCodes`；当前没有逐码解释及独立关节故障规则 |

上肢配置变量为 `ROS_JOINT_STATES_TOPIC`、`ROS_LEFT_TCP_TOPIC`、`ROS_RIGHT_TCP_TOPIC`、`ROS_UPPERLIMB_STATE_TOPIC`。实机不要配置 `/fake/upperlimb/...`。

## 3. 两组电池和续航

| 页面数据 | topic / 来源 | 消息类型与字段 |
| --- | --- | --- |
| 电池 1 电量、电压、电流、温度 | 默认 `/zj_humanoid/robot/battery_state`、`/zj_humanoid/robot/battery_info`；安装配置额外订阅 `/web/battery_info` | `sensor_msgs/msg/BatteryState`：`percentage × 100`、`voltage`、`current`、`temperature` |
| 电池 1 的底盘补充读数 | `/zj_humanoid/chassis/agv_state`，兼容 `/chassis/agv_state` | `chassis_msgs/msg/AGVNewState`：`battery_percentage × 100`、`battery_voltage`、`battery_current`；该消息不补充温度或容量 |
| 电池 2 电量、电压、电流、温度 | 默认 `/robot/battery2_info`、`/zj_humanoid/robot/battery2_info`；其它名称用 `ROS_BATTERY2_TOPICS` 补充 | `sensor_msgs/msg/BatteryState`，与电池 1 字段相同，单独保存和展示 |
| 单体电压显示值 | 各自 `BatteryState.cell_voltage` | 当前取有效数组值的平均值；不是逐节电压列表，没有数组时为 `--` |
| 充电状态 | 各自有效电压、电量、电流 | 由后端推断，当前不依赖 `power_supply_status`：默认负电流小于 -0.2 A 为充电，正电流大于 0.2 A 为放电；死区内且电量 ≥99.5% 为已充满，否则为未充电 |
| 两组预计续航 | 各自 `BatteryState.charge`、`capacity`、`percentage`、`current` | 优先用有效 `charge`（Ah），否则以有效 `capacity × percentage` 得剩余 Ah；剩余 Ah / 近期平均放电电流 × 60 得分钟，两组独立计算 |
| 本次开机运行时长 | Pico 本机 `/proc/uptime` | 本次系统开机时长；不是电机使能时长，也不是某个搬运任务时长 |

续航窗口默认最近 20 分钟（`BATTERY_AVERAGE_WINDOW_SECONDS=1200`），按采样间隔加权平均，不是最近 20 次采样。启动初期使用已有样本，至少积累 5 秒有效时间；充电、容量缺失、电流过小或消息过期时显示 `--`。重启后端会重新积累电流样本，开机运行时长不因此归零。

`BATTERY_DISCHARGE_SIGN=1` 表示正电流为放电；现场电流方向相反时设为 `-1`。无有效包电压（≤1 V）的默认帧不作为电池读数，温度超出 -40～100°C 会丢弃。

## 4. Orin / Pico 计算资源与 IP

| 页面数据 | 来源 | 消息类型 / 处理 |
| --- | --- | --- |
| Orin CPU、内存、磁盘、GPU、温度 | `/zj_humanoid/robot/orin_states/resource` | `navi_robot_msgs/msg/Resource` 或 `robot_msgs/msg/Resource`：`cpu_usage`、`memory_usage`、`disk_usage`、`gpu_usage`、`temperature` |
| Orin CPU 均值 | `/zj_humanoid/robot/orin_states/diagnostics_agg` 中的 `/jtop/CPU/cpu*` 项 | `diagnostic_msgs/msg/DiagnosticArray`；取有效核心使用率的算术平均值，优先于 resource 的 CPU 字段 |
| Pico 资源 | `/zj_humanoid/robot/pico_states/resource`；安装时也配置 `LOCAL_RESOURCE_SOURCE=pico` 定时采集本机 | 同上 Resource；本机采集从 `/proc/stat` 计算 CPU 总体占用，从 `/proc/meminfo`、根文件系统及 `/sys/class/thermal/` 读取内存、磁盘和温度 |
| Pico GPU | 当前不提供读数 | `gpuUsage=null`，页面显示 `--` |
| 资源异常标志 | `/zj_humanoid/robot/orin_states/errors`、`/zj_humanoid/robot/pico_states/errors` | `navi_robot_msgs/msg/Errors` 或 `robot_msgs/msg/Errors`；背屏还基于有效资源值执行自己的阈值检查 |
| Pico IP、网络状态 | Pico 本机网卡 | 通过 `ip` 和 `/sys/class/net/` 读取；可用 `NETWORK_INTERFACE` 指定网卡。本机网卡在线不表示已收到 ROS 数据 |
| Orin IP | `ORIN_IP` 配置；已有可选 Orin HTTP 后端时也可由其快照提供 | 用于页面地址展示；按实际设备地址配置 |
| 型号 | `ROBOT_MODEL`；可选 `/zj_humanoid/robot/basic_info` 服务 | `navi_robot_msgs/srv/BasicInfo` 或 `robot_msgs/srv/BasicInfo`；服务返回非空型号时更新配置的兜底值 |

若没有有效的逐核诊断，Orin CPU 会使用 `Resource.cpu_usage` 原值；它是最大值还是平均值由发布端定义，背屏不能仅凭这个单值重新算均值。

## 5. 相机、雷达、六维力、碰撞条

| 在线状态 | topic / 配置 | 类型 | 页面判断方式 |
| --- | --- | --- | --- |
| 雷达① | 默认 `/zj_humanoid/chassis/laser_scan`；`ROS_LIDAR_1_TOPIC` 覆盖 | `sensor_msgs/msg/LaserScan` | 收到扫描消息后记录时间，超时判离线；当前不在背屏绘制扫描图 |
| 雷达② | `ROS_LIDAR_2_TOPIC`，默认留空，需填第二台实际扫描话题 | `sensor_msgs/msg/LaserScan` | 与雷达①独立记录；一条扫描话题不拆成两台雷达 |
| 可选点云雷达流 | `ROS_LIDAR_POINTCLOUD_TOPIC`，默认留空 | `sensor_msgs/msg/PointCloud2` | 仅显式配置后订阅，用于汇总雷达在线状态 |
| 深度相机 | 安装配置 `/zj_humanoid/sensor/realsense_head/depth/image_rect_raw`；`ROS_DEPTH_CAMERA_TOPIC` | 图像话题，通常 `sensor_msgs/msg/Image` | 每 2 秒查询发布者，避免在 Pico 持续解码高带宽图像 |
| 头部彩色相机 | 安装配置 `/zj_humanoid/sensor/realsense_head/color/image_raw`；`ROS_CAMERA_TOPIC` | 同上 | 查询发布者 |
| 左腕相机 | `/zj_humanoid/sensor/left_wrist/color/image_raw`；`ROS_LEFT_WRIST_CAMERA_TOPIC` | 同上 | 查询发布者 |
| 右腕相机 | `/zj_humanoid/sensor/right_wrist/color/image_raw`；`ROS_RIGHT_WRIST_CAMERA_TOPIC` | 同上 | 查询发布者 |
| 六维力 | `/zj_humanoid/hand/wrist_force_sensor/left`、`right` | `geometry_msgs/msg/WrenchStamped` | 收到腕力消息即刷新汇总在线状态；任一侧持续更新可使汇总灯在线，左右具体值分开保存 |
| 碰撞条 | `/zj_humanoid/chassis/agv_state`，兼容 `/chassis/agv_state` | `chassis_msgs/msg/AGVNewState.collision` | `true` 为触发，`false` 为未触发；该反馈不等于独立碰撞条硬件在线位 |

相机绿灯仅表示发布者存在，不保证真实图像正常。雷达与六维力使用消息到达时间，默认传感器超时 3 秒（`ROS_SENSOR_TIMEOUT_SECONDS`）；运动、电池等数值默认过期阈值为 5 秒（`ROS_DATA_STALE_SECONDS`）。

## 6. 复位、诊断和日志接口

| 数据 / 操作 | 接口 | 类型与用途 |
| --- | --- | --- |
| 急停和底盘状态 | `/zj_humanoid/chassis/agv_state` | `chassis_msgs/msg/AGVNewState`：`emergency`、`state`、`description`；`emergency=true` 为急停触发 |
| 复位按钮可用条件及结果 | `/zj_humanoid/back_screen/reset_status` | `std_msgs/msg/String`，JSON 含 `state`、`requestId`、`resetAllowed`、`blockReasons`、`feedbackFresh`、`motionGate` |
| 网页请求复位 | `POST /api/v1/commands/chassis-reset` → `/zj_humanoid/back_screen/reset` | 后者为 `std_srvs/srv/Trigger`，由我们部署在 Orin 的主控提供 |
| 主控向底盘发送复位 | `/zj_humanoid/chassis/agv_reset` | `std_srvs/srv/Trigger`，底盘中间件负责实际 `resetCommand`；网页不直接绕过主控调用它 |
| 复位后确认新任务 | `/zj_humanoid/back_screen/confirm_new_task` | `std_srvs/srv/Trigger`，人工或任务系统主动调用；不是自动轮询接口 |
| ROS 原始诊断 | 默认 `/diagnostics`、`/zj_humanoid/robot/diagnostics`、`/zj_humanoid/robot/diagnostics/robot_state_node`、Orin/Pico 的 `diagnostics_agg` | `diagnostic_msgs/msg/DiagnosticArray`；`ROS_DIAGNOSTICS_TOPICS` 可覆盖此列表 |
| 运行日志 | `/rosout`，以及后端诊断/复位操作记录 | `rcl_interfaces/msg/Log`；后端最多缓存最近 200 条，通过 `/api/v1/history` 提供 |

`ROS-1/2/3` 通用诊断项保留底层订阅，不进入背屏实时告警列表、告警计数和首页健康等级。具体资源和设备离线告警默认持续 5 秒后显示，恢复后自动移除。CPU 默认阈值为 95%，内存/磁盘 90%，GPU 95%，计算资源温度 80°C；温度 ≥90°C 为严重告警。这些不是关节电机的温度阈值。

## 7. 当前没有直接数据来源的项目

| 字段或需求 | 当前实现 |
| --- | --- |
| 目标点 | `motion.target` 预留为空，尚未订阅导航目标反馈；背屏不设置目标点 |
| 末端负载 | `payloadKg` 预留为空，未调用 payload 服务读取实际负载 |
| 夹爪夹持力 | 当前没有订阅 `/zj_humanoid/gripper/left/state`、`right/state` 或 `/zj_humanoid/hand/finger_pressures/left`、`right`；存在话题也不会自动出现在本页面。左右腕合力不能替代夹持力 |
| 电池循环次数 | `cycles` 预留为空，当前适配器未接入循环次数来源 |
| 自动/手动作业模式 | 无统一已接入来源；页面当前使用机器人状态文字，或显式接入 WorkStatus 的 `mode` |
| 作业时长、耗电 Ah、平均电流、任务次数、重量、负载率 | 本地 `/api/v1/work-summary` 当前返回空字段和空任务列表，尚未订阅能完整生成作业记录的 topic；仅连接充电器不会自动生成搬运记录 |

作业总结页面已具备展示和计算逻辑：耗电为上次充电结束 Ah 减本次充电触发 Ah；时长为两时间戳之差（秒）；平均电流为耗电 Ah / 时长小时数；任务数取任务明细条数，总重量与负载率需要完整任务重量和额定负载。只有外部数据源提供这些输入时才有结果。

## 8. 查看原始消息

在对应机器加载中间件后，可把下面的关节话题替换为上表任意 topic：

```bash
# Pico；Orin 则加载 /etc/naviai/Middleware.env
source /etc/nav01/Middleware.env
source /opt/ros/humble/setup.bash
ros2 topic type /zj_humanoid/upperlimb/joint_states
ros2 topic info -v /zj_humanoid/upperlimb/joint_states
ros2 topic echo --once /zj_humanoid/upperlimb/joint_states
```

看到话题名不代表有数据；类型要与实际发布者匹配。若 `chassis_msgs` 缺失，Pico 安装脚本会按需构建 `deploy/ros_interfaces/chassis_msgs` 到 `/opt/robot-back-screen/ros_interfaces`，启动 API 时加载该私有接口。它只提供消息解码，不会安装或启动底盘驱动。
