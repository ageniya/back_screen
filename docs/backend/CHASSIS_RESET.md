# 背屏急停复位使用与实现

更新日期：2026-11-11。本文描述仓库实现；日常启动、关闭和页面操作见 [使用说明](../背屏交付与使用手册.md)，topic 对照见 [数据来源](ROS_MAIN_FIELD_MAPPING.md)。

本项目实现复位主控，不再等待外部联锁服务。Pico 后端处理网页请求，Orin 上的 `robot-motion-supervisor` 负责实际运动门控、导航任务取消、复位调用和反馈状态机。

## 调用链路

```text
Pico 背屏（按钮二次确认）
  → POST /api/v1/commands/chassis-reset
  → /zj_humanoid/back_screen/reset（Trigger，我们实现）
  → 运动锁定、速度目标归零、记录旧任务中断、取消全部导航目标
  → /zj_humanoid/chassis/agv_reset（Trigger，底盘中间件）
  → 读取 agv_state，确认复位结果；不会自动恢复旧任务
```

所有状态和按钮条件由 `/zj_humanoid/back_screen/reset_status`（`std_msgs/msg/String` JSON）提供。背屏还会再次检查本机收到的底盘反馈和速度新鲜度。

复位按钮使用页面内的二次确认框，不受浏览器“禁止后续弹窗”设置影响。请求处理中禁止重复发送，完成后按钮自动置灰；旧 HTTP 快照不能重新点亮按钮。页面没有软件急停按钮和独立的启动按钮。

Orin 安装脚本将底盘的三路 ROS 运动订阅重映射为门控出口：

| 原入口（门控订阅） | 底盘实际订阅的门控出口 |
| --- | --- |
| `/zj_humanoid/cmd_vel/calib` | `/zj_humanoid/back_screen/motion/cmd_vel` |
| `/zj_humanoid/cmd_vel/manual` | `/zj_humanoid/back_screen/motion/manual` |
| `/zj_humanoid/chassis/steer_command` | `/zj_humanoid/back_screen/motion/steer` |

门控会检查真实 DDS 订阅关系。有直接绕过门控的底盘订阅、缺失出口或其它出口发布者时，拒绝复位。此实现覆盖上述底盘 ROS 运动链路；不声称接管独立的上肢 SDK 或厂家底层直接控制通道。

## 条件与状态

首次有效反馈 emergency=true 进入 E_STOP_ACTIVE，false 进入 E_STOP_RELEASED；首次启动绝不自动复位或放行运动。急停回调立即锁门并发送零速度。未收到有效状态、状态超过 3 秒未更新、未确认静止时不允许复位。

按 FR-02，静止采用未四舍五入的线速度和角速度全部分量检查（容差 1e-4）。碰撞条保留真实显示，不作为额外复位限制。

人工确认后，主控立即锁住运动、清空速度目标、将已知活动导航目标标记为“已中断，需重新确认”，原子保存任务中断记录，然后取消 Navigation action 服务端的全部目标。确认旧目标已结束后，再发送底盘复位。锁定期间到达的速度/舵轮命令直接丢弃、不排队、不重放。

RESET_REQUESTED 状态禁止重复请求。完成判定必须同时满足：底盘复位服务返回成功，且已收到发送复位指令之后的新鲜有效状态反馈。服务回执与状态话题可以以任意顺序到达，先到的反馈会保留，不要求再次点击复位。已知非 ERROR 状态进入 RESET_DONE；ERROR+“等待复位”保持等待；其它 ERROR 保持锁定并报错。发送前的旧反馈、过期反馈及 HTTP 请求受理本身都不能证明复位完成。2 秒硬件延迟仍由底盘执行，主控没有用睡眠代替反馈。

默认复位超时 10 秒，可用 ROS_RESET_TIMEOUT_SECONDS 配置。通信中断时保持请求到超时，不假设成功；有效通信恢复并满足静止等条件后才允许人工重试。其它底盘故障必须先由反馈确认解除。复位服务为 Trigger 空请求，对应底盘默认 resetType=0；服务类型不能携带其它 resetType，需扩展底盘接口后才支持其它值。

## 复位后重新下发任务

RESET_DONE 只表示底盘复位完成，门控仍保持锁定，旧任务绝不自动继续。没有新增网页启动按钮。任务软件或操作员必须明确确认新任务，然后重新下发任务：

```bash
# 仅在现场确认安全、复位完成、机器人静止、没有旧活动任务时调用。
ros2 service call /zj_humanoid/back_screen/confirm_new_task std_srvs/srv/Trigger "{}"
```

此确认不恢复任何已取消任务。它会开放后续新的运动指令，不能作为只读查询或自动轮询调用。新任务系统应在收到人工确认后调用它。

## 安装与启动

Orin：`robot-motion-supervisor.service`，代码位于 `/opt/robot-back-screen-control`。服务启动即锁定；systemd 看门狗监测主控心跳，异常退出后独立停止辅助进程向门控出口发送零速度，再重启主控。命令源停更 0.5 秒也发送零速度。

安装脚本检查实际运行的 `zj-humanoid-chassis.service` 或 `zj-humanoid-orin-chassis-supervisor.service`，确认连续静止、备份 chassis.launch.py，配置三路重映射，再重启该服务。

```bash
# 在包含本项目源码的 Orin 目录运行。会改变底盘 ROS 路由并保持锁定。
bash deploy/install.sh orin
```

Pico 的 `deploy/start-pico-api.sh` 加载 ROS 环境，安装配置在 `/etc/robot-back-screen/env` 设置 `ROS_ENABLE_RESET=true`。该开关只开放人工复位，不会同时开放软件急停接口。

安装脚本会为 Pico API、Pico 显示和 Orin 主控启用开机自启动。安装后手动启动使用 `bash deploy/start.sh pico` / `bash deploy/start.sh orin`。

## 查看状态与日志

```bash
# Orin
systemctl status robot-motion-supervisor.service
journalctl -u robot-motion-supervisor.service -n 60 --no-pager

# 加载对应 ROS2 环境后，查看主控反馈；此命令只订阅状态
ros2 topic echo --once /zj_humanoid/back_screen/reset_status
```
