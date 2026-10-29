# 背屏字段与 NAVI ROS2 SDK `main` 接口映射

本文以 `navi_ros2_sdk` 的 `origin/main` 和 chassis / robot 联调文档为准。统一后端部署在机器人 ROS 2 环境中，订阅/调用这些接口后，再向背屏、平板和管理后台提供 HTTP 数据；浏览器不直接访问 ROS。

现场节点、实际消息类型和可读取数据以 [2026-10-14 实机排查](2026-10-14_实机话题与数据排查.md) 为准。
规范中的接口不等于当前镜像已经持续发布；报告同时记录原始消息、背屏映射及未展示的数据。

## 先确认机器人名前缀

接口示例中的 `/zj_humanoid` 不是固定值。实机上先运行 `echo $ROBOT_NAME`；若结果为 `zj_humanoid_5001`，则真实接口为 `/zj_humanoid_5001/...`。

ROS 适配器优先读取 `ROBOT_NAME`，也可通过 `ROS_NAMESPACE` 显式覆盖。不要将示例前缀直接写死。

## 可直接接入

| 背屏字段 | ROS 接口 | 数据处理方式 |
| --- | --- | --- |
| 机器人型号、IP、软硬件版本 | `/zj_humanoid/robot/basic_info` 服务 | 读取 `robot_model`、`ip_address` 等返回字段；启动时及重连后查询。 |
| 机器人状态 | `/zj_humanoid/robot/robot_state` | 读取 `state`、`state_info`，用于运行/停止/故障状态。 |
| 作业模式、任务、进度 | 待实机确认 | 当前实际对外接口文档未列出统一作业状态 topic。 |
| 电量、电压、电流、温度 | Pico：`/robot/battery_state`；WA：`/robot/battery_info` | 两者均为标准 `sensor_msgs/BatteryState`；`percentage` 为 0~1，后端转换为百分比。 |
| 关节角度、3D 姿态 | `/zj_humanoid/upperlimb/joint_states` | `sensor_msgs/msg/JointState`，已确认实际接口；需要底层 SDK 与上肢节点完成初始化后发布。 |
| 左右手 TCP 位姿 | `/zj_humanoid/upperlimb/tcp_pose/left_arm`、`right_arm` | `upperlimb_msgs/msg/Pose`，已确认接口，按显式部署配置订阅。 |
| 关节温度 | `/zj_humanoid/robot/joint_motor/temperatures` | `sensor_msgs/JointState.effort` 存放温度值。 |
| 关节错误码 | `/zj_humanoid/robot/joint_motor/errors` | `sensor_msgs/JointState.effort` 存放错误码。 |
| 腕部六维力 | `/zj_humanoid/hand/wrist_force_sensor/left`、`right` | `geometry_msgs/msg/WrenchStamped`，可显示 Fx/Fy/Fz、Mx/My/Mz 或计算腕部合力。 |
| 底盘位置与速度 | `/chassis/odom_info` | `nav_msgs/msg/Odometry`；后端读取 `pose.pose.position` 和 `twist.twist.linear`，静止时零值正常，超过 5 秒无消息显示 `--`。 |
| 底盘电量、电压、电流 | `/chassis/agv_state` | `chassis_msgs/msg/AGVNewState` 的 `battery_percentage`（0~1，转换为 %）、`battery_voltage`（V）、`battery_current`（A）；不推算温度或充电状态。 |
| 开机运行时长 | Pico 本机 `/proc/uptime` | 本次开机累计时长，重启背屏后端不归零；不等于电机使能时间或任务作业时长。 |
| 预计续航 | 第一组 `/web/battery_info` | `charge`（Ah）除以最近 20 分钟平均放电电流（A），乘 60 得分钟；使用已有窗口样本，不伪造满 20 分钟历史。 |
| 底盘状态、急停反馈、碰撞反馈 | `/chassis/agv_state` 或 `/zj_humanoid/chassis/agv_state` | `state`、`description`、`emergency`、`collision` 写入 `diagnosticMetrics.chassisState`；碰撞反馈映射为碰撞条状态。该字段不能证明独立碰撞条硬件在线。 |
| 系统、关节、电池总体诊断 | `/diagnostics_agg` | `diagnostic_msgs/DiagnosticArray`；由官方 `diagnostic_aggregator` 汇总，作为健康状态和告警来源。 |
| 系统资源 | `/zj_humanoid/robot/orin_states/resource` 或 `/zj_humanoid/robot/pico_states/resource` | CPU、内存、磁盘、温度、GPU 使用率。 |
| 系统资源阈值异常 | `/zj_humanoid/robot/orin_states/errors` 或 `/zj_humanoid/robot/pico_states/errors` | 过温、CPU、内存、磁盘告警标记。 |
| 底盘软急停 | `/zj_humanoid/chassis/soft_estop` 服务 | `std_srvs/srv/Trigger`；可用 `ROS_STOP_SERVICE` 覆盖，默认关闭实机控制。具体名称和实际行为需要现场验证。 |
| 底盘复位 | `/zj_humanoid/chassis/agv_reset` 服务 | `std_srvs/srv/Trigger`；底盘中间件负责发送 `resetCommand`。背屏复位状态机通过此服务请求底盘复位；实际调用前必须完成主控运动联锁，见 [接入说明](CHASSIS_RESET.md)。 |
| 恢复 | `/zj_humanoid/robot/recover` 服务 | 真实接入后调用 `std_srvs/Trigger`；只用于满足恢复条件后的动作。 |

## 通过“消息是否持续到达”判断在线状态

这些接口本身是数据流，统一后端记录最后接收时间；超过阈值未收到消息时显示为离线/异常。

| 背屏传感器状态 | ROS 接口 |
| --- | --- |
| 激光雷达 | WA1：`/zj_humanoid/chassis/laser_scan`；其他型号接机时确认 |
| 深度相机 | `/zj_humanoid/sensor/{camera_name}/depth/image_rect_raw` |
| 摄像头 | `/zj_humanoid/sensor/{camera_name}/image_raw` 或压缩图像话题 |
| 六维力 | `/zj_humanoid/hand/wrist_force_sensor` |

## 暂无明确 SDK 来源，接机时确认

以下字段不应伪造为真实值；在实机模式下，后端应返回 `null`，前端显示 `--`，直到确认来源。

| 字段 | 原因 / 后续确认项 |
| --- | --- |
| 目标点 | 实际接口文档未提供统一的“当前目标点反馈”话题。 |
| 末端负载 | 存在 `/zj_humanoid/upperlimb/payload/get` 服务，需确认返回类型和“当前实际负载”语义。 |
| 夹持力 | 腕部六维力不等同于夹持力，需确认手部夹持力接口。 |
| 单体电压、充电循环次数 | 当前 `BatteryState` / 已见电源状态接口未定义这两项。 |
| 满负载保证续航 | 当前页面仅估算近期负载下的续航，不能作为额定满负载续航指标。 |
| 本次作业时长、搬运次数、负载汇总 | `WorkStatus` 提供任务和进度；完整统计字段需确认任务系统接口。 |
| 独立碰撞条硬件在线状态 | 底盘 `AGVNewState.collision` 提供整机碰撞反馈，未提供独立碰撞条设备在线位。 |

## 2026-10-14 WA-T 实机底盘配置

Orin 已确认实际发布 `/chassis/odom_info` 和 `/chassis/agv_state`。旧 `/web/odom_info`
中继订阅 `/navigation/odom_info`，该上游当前无发布者，因此背屏直接订阅底盘原始话题：

```bash
export ROS_ODOM_TOPICS=/chassis/odom_info
export ROS_CHASSIS_STATE_TOPICS=/chassis/agv_state
```

Pico 缺少 `chassis_msgs` 时，可在 Pico 的背屏源码目录执行：

```bash
bash deploy/build-chassis-interface.sh /home/nav01/back-screen-preview/ros_interfaces
source /home/nav01/back-screen-preview/ros_interfaces/install/setup.bash
```

`deploy/ros_interfaces/chassis_msgs` 只包含 Orin 已安装的 2.0.0 版 `AGVNewState`
消息定义，用于在 Pico 本机生成对应架构的解码库；不会安装底盘驱动。已有完整
`chassis_msgs` 包时直接使用它，不加载接口子集。实际 Pico 的 `start-screen.sh`
已在缺少该类型时加载这个私有目录，开机启动沿用同一配置。

使用仓库 `deploy/robot-back-screen-api.service` 部署时，也可在其 EnvironmentFile 中设置
`ROS_INTERFACES_SETUP=/home/nav01/back-screen-preview/ros_interfaces/install/setup.bash`。
标准 `BatteryState` 若也开始发布有效数据，可补充电池温度、单体电压和充电状态；
这些扩展字段独立判断消息新鲜度，不能因底盘三项电池数据仍在更新而保留过期值。

## 接机实施顺序

1. 在真实机器人上运行 `echo $ROBOT_NAME`，确认接口前缀；再运行 `ros2 topic list`，确认上述名称是否存在。
2. 使用 `ros2 topic echo <话题名> --once` 核对实际消息字段和值域。
3. 在统一后端添加 ROS 2 订阅适配器；使用真实 ROS 数据，未收到数据时显示未知。
4. 后端将 ROS 原始消息转换为 `/api/v1/robot/snapshot`、`/api/v1/alarms` 的稳定格式。
5. 背屏无需改动，只将数据源切换为后端实机模式。

### 当前后端的接机配置

已在后端写入的电池、里程计、机器人状态、基础信息、资源和诊断接口会根据
`ROBOT_NAME` 自动拼接前缀。上肢接口尚未在实际文档中确认，接机核对后再显式配置，
例如：

```bash
export ROS_JOINT_STATES_TOPIC='/实际的关节话题'
export ROS_LEFT_TCP_TOPIC='/实际的左手末端位姿话题'
export ROS_RIGHT_TCP_TOPIC='/实际的右手末端位姿话题'
```

Pico 实机已经确认的上肢接口为：

```bash
export ROS_JOINT_STATES_TOPIC='/zj_humanoid/upperlimb/joint_states'
export ROS_LEFT_TCP_TOPIC='/zj_humanoid/upperlimb/tcp_pose/left_arm'
export ROS_RIGHT_TCP_TOPIC='/zj_humanoid/upperlimb/tcp_pose/right_arm'
```

`joint_states` 是标准 `sensor_msgs/msg/JointState`，已验证包含双臂、颈部和升降轴共 17 个关节；左右 TCP 使用 `upperlimb_msgs/msg/Pose`。`/fake/upperlimb/...` 是示教/仿真接口，不能配置到实机背屏。未配置时，背屏 3D 姿态和左右手 TCP 显示为 `--`，不会把猜测数据当成实机数据。

## 诊断边界

`main` 已提供 ROS 标准诊断汇总：`/diagnostics -> /diagnostics_agg`。它足以支撑背屏健康状态和基础异常展示。

用户规则协议中的 YAML / WebSocket 动态规则引擎未在 `main` 中找到。规则管理后台接入该能力前，仍需确认其独立部署位置、WebSocket URL、鉴权方式和实际运行状态。
