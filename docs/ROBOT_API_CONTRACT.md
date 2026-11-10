# 背屏机器人数据接口契约（v1）

更新日期：2026-11-11。本文描述当前前后端字段与接口。日常操作见 [使用说明](背屏交付与使用手册.md)，ROS2 数据来源见 [topic 对照](backend/ROS_MAIN_FIELD_MAPPING.md)。正式部署使用 Pico HTTP API；`window.ROBOT_DATA_ADAPTER` 作为额外接入方式保留。

## 1. HTTP 接口

开发环境可由 `frontend/public/runtime-config.js` 或地址参数指定接口前缀；统一部署时，背屏通过同一 8000 服务自动使用 `${window.location.origin}/api/v1`。

| 用途 | 方法与路径 |
| --- | --- |
| 实时快照 | `GET /robot/snapshot` |
| 当前告警 | `GET /alarms` |
| 本次作业总结 | `GET /work-summary` |
| 真实运行日志 | `GET /history` |
| 刷新诊断 | `POST /commands/diagnose` |
| 底盘软件急停 | `POST /commands/soft-stop` |
| 底盘复位 | `POST /commands/chassis-reset` |
| 确认恢复告警 | `POST /alarms/:id/acknowledge` |
| 清除已恢复告警 | `POST /alarms/clear-recovered` |

复位/软件停止接口返回 `accepted`、`commandId` 和 `message`。`accepted=true` 仅表示请求已受理；实际动作和最终状态必须由后续快照确认，不能据此显示“已复位”。具体返回结构也可在运行中的 `/docs` 查看。

底盘软件急停使用 `ROS_STOP_SERVICE` 指定的 `std_srvs/srv/Trigger` 服务，默认 `/zj_humanoid/chassis/soft_estop`。当前页面不提供软件急停按钮。

复位状态由 Orin 主控根据 AGVNewState 派生，再经 `/{ROBOT_NAME}/back_screen/reset_status` 传给 Pico。快照的 `controlState` 为 `E_STOP_ACTIVE`、`E_STOP_RELEASED`、`RESET_REQUESTED`、`RESET_DONE` 之一，未收到反馈时为空。`chassisReset` 包含 `requestId`、`resetAllowed`、`blockReason`、`blockReasons`、`error`、`feedbackFresh`、`motionInterlockReady`、`checks` 和 `motionGate`。前端使用页面内二次确认框；处理中禁止重复发送，完成后自动禁用按钮。

复位由本项目的 `robot-motion-supervisor` 执行。HTTP 后端调用我们自己的 `/{ROBOT_NAME}/back_screen/reset`（Trigger），主控完成运动门控、导航目标取消及任务中断记录后，才调用底盘 `agv_reset`。界面受理不代表底盘已复位，最终结果看后续快照。

`ROS_ENABLE_RESET` 独立控制人工复位权限；`ROS_ENABLE_CONTROL` 仍用于原有软件停止接口。完整流程、三路底盘运动出口、复位后新任务确认及现场验收方法见 [急停复位实现](backend/CHASSIS_RESET.md)。

## 2. 实时快照

前端每秒请求一次 `GET /robot/snapshot`。可直接返回对象，也可包在 `{ "data": { ... } }` 中。下面只示意字段结构，不代表实机读数；没有来源的值返回 `null`，不能以示例值填充。

```json
{
  "robotModel": "WA-T",
  "health": { "level": "normal", "label": "系统健康", "alertCount": 0 },
  "motion": {
    "position": "X1.23 Y2.34 Z0.56",
    "target": null,
    "speed": "0.45 m/s",
    "leftTcp": "X1.23 Y2.62 Z0.56",
    "rightTcp": "X1.23 Y2.06 Z0.56",
    "joints": [15, 23, -8, 42, 11, 5],
    "jointPositions": {
      "Shoulder_X_L": 1.35,
      "Shoulder_X_R": -1.35
    }
  },
  "payloadKg": null,
  "gripForceN": null,
  "operationMode": "运行中",
  "uptime": "2h23m",
  "battery": {
    "percent": 85,
    "remainingMinutes": 42,
    "voltage": 14.8,
    "current": 3.2,
    "temperature": 28,
    "cellVoltage": 3.7,
    "chargeStatus": "充电中",
    "cycles": null
  },
  "battery2": { "percent": null, "voltage": null, "current": null, "remainingMinutes": null },
  "controlState": null,
  "chassisReset": { "state": null, "resetAllowed": false, "feedbackFresh": false },
  "wristForces": { "left": null, "right": null },
  "sensors": {
    "lidar": true,
    "depthCamera": true,
    "forceSensor": true,
    "bumper": "online",
    "camera": true,
    "network": true
  },
  "network": { "ip": "192.168.1.10", "signalStrength": -55 }
}
```

`health.level` 使用 `normal`、`info`、`warning`、`critical`、`emergency`。电池 1 / 2 分别计算 `remainingMinutes`：有效剩余 Ah 除以最近 20 分钟时间加权平均放电电流，再乘 60；充电、样本不足或数据无效时返回 `null`。前端不自行推算续航。

`operationMode` 当前主要是 RobotState 的状态文字，不保证代表“自动/手动”。`payloadKg`、`gripForceN`、`cycles` 当前未接入。页面的左右腕合力分别从 `wristForces.left/right.force` 计算 `sqrt(Fx²+Fy²+Fz²)`，不是夹爪夹持力。

`motion.leftTcp`、`motion.rightTcp` 分别是左、右手末端工具中心点（TCP）的 XYZ 坐标。双臂机器人必须分别提供；旧字段 `motion.tcp` 只为旧版调用方兼容保留，新页面不再显示它。

`motion.jointPositions` 用于 3D 视图：键为 URDF 关节名，值为 ROS2 原始弧度值（直线关节为米）。收到该字段后，模型跟随该组姿态；消息过期时清空实时关节数据。无数据时模型的展示姿态不能作为实机状态。`motion.position` 保留里程计的坐标系语义，前端不把它改为背屏启动时的零点。

`sensors.bumper` 为碰撞条三态：`online`（绿色，在线未碰撞）、`triggered`（黄色，已碰撞）、`offline`（红色，不在线）。为兼容旧适配器，布尔值 `true` 等同 `online`，`false` 等同 `offline`。

未收到消息时传感器值可为 `null`。相机的 `headCamera`、`leftWristCamera`、`rightWristCamera` 通过查询发布者判断；雷达的 `lidar1`、`lidar2` 通过接收扫描消息判断。默认过期数值显示 `--`。

## 3. 告警与作业数据

告警项至少包含 `id`、`code`、`severity`、`title`、`time`、`desc`、`suggestion`。`severity` 使用 `info`、`warning`、`critical`、`emergency`。

`ROS-1`、`ROS-2`、`ROS-3` 通用诊断项在合并 Pico/Orin 告警后过滤，不进入告警列表、计数和首页健康等级。具体告警默认持续 5 秒才显示，恢复后自动移除；确认恢复接口不能清除仍然触发的故障。

作业总结预留 `lastChargeAh`、`triggerAh`、`lastChargeEndTs`、`chargeStartTs`、`ratedLoad` 和 `tasks`；任务项使用 `name`、`weight`、`time`。可额外提供 `consumptionAh`、`durationSec`、`avgCurrent`。时间戳按秒提供；页面可用 Ah 差与时间差计算耗电和平均电流。

当前本地后端没有完整作业记录来源，返回空字段和空任务数组。连接充电器不会自动创建搬运记录；配置 `ORIN_API_BASE` 时，也可使用该已有 HTTP 后端的作业总结结果。

## 4. 非 HTTP 接入

若机器人已有 ROS2 WebBridge 或 SDK 包装层，可在加载页面前注入：

```js
window.ROBOT_DATA_ADAPTER = {
  getSnapshot: async () => snapshot,
  getAlarms: async () => alarms,
  getWorkSummary: async () => workSummary,
  sendCommand: async (path, body) => ({ accepted: true, commandId: '...' })
};
```

无论采用何种方式，均应由机器人侧适配已有控制器、BMS、传感器和诊断节点；背屏只使用上述统一数据结构。
