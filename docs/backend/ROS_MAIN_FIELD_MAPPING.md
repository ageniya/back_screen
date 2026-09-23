# 背屏字段与 NAVI ROS2 SDK `main` 接口映射

本文以 `navi_ros2_sdk` 的 `origin/main` 和 chassis / robot 联调文档为准。统一后端部署在机器人 ROS 2 环境中，订阅/调用这些接口后，再向背屏、平板和管理后台提供 HTTP 数据；浏览器不直接访问 ROS。

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
| 关节角度、3D 姿态 | 待实机确认 | 当前实际对外接口文档未展示上肢关节状态 topic。 |
| 左右手 TCP 位姿 | 待实机确认 | 当前实际对外接口文档未展示上肢末端位姿 topic，不猜测名称。 |
| 关节温度 | `/zj_humanoid/robot/joint_motor/temperatures` | `sensor_msgs/JointState.effort` 存放温度值。 |
| 关节错误码 | `/zj_humanoid/robot/joint_motor/errors` | `sensor_msgs/JointState.effort` 存放错误码。 |
| 腕部六维力 | `/zj_humanoid/hand/wrist_force_sensor` | 读取 `hand_msgs/WristForceSensor`，可显示 Fx/Fy/Fz、Mx/My/Mz 或计算合力。 |
| 底盘位置与速度 | `/chassis/odom_info` | `nav_msgs/Odometry`；后端读取 `pose.pose.position` 和 `twist.twist.linear`。 |
| 系统、关节、电池总体诊断 | `/diagnostics_agg` | `diagnostic_msgs/DiagnosticArray`；由官方 `diagnostic_aggregator` 汇总，作为健康状态和告警来源。 |
| 系统资源 | `/zj_humanoid/robot/orin_states/resource` 或 `/zj_humanoid/robot/pico_states/resource` | CPU、内存、磁盘、温度、GPU 使用率。 |
| 系统资源阈值异常 | `/zj_humanoid/robot/orin_states/errors` 或 `/zj_humanoid/robot/pico_states/errors` | 过温、CPU、内存、磁盘告警标记。 |
| 急停 | Pico：`/robot/stop`；WA：`/chassis/soft_estop` 服务 | 均为 `std_srvs/Trigger`；通过 `ROS_STOP_SERVICE` 选择，必须有权限控制和二次确认。 |
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
| 剩余续航 | 需要产品确认估算算法（通常为剩余电量除以近一段时间平均耗电）。 |
| 本次作业时长、搬运次数、负载汇总 | `WorkStatus` 提供任务和进度；完整统计字段需确认任务系统接口。 |
| 碰撞条 | `main` 当前已见接口中未找到明确碰撞条状态。 |

## 接机实施顺序

1. 在真实机器人上运行 `echo $ROBOT_NAME`，确认接口前缀；再运行 `ros2 topic list`，确认上述名称是否存在。
2. 使用 `ros2 topic echo <话题名> --once` 核对实际消息字段和值域。
3. 在统一后端添加 ROS 2 订阅适配器；保留当前 `mock` 模式，便于无实机开发和演示。
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
