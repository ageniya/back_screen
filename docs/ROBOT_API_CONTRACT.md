# 背屏机器人数据接口契约（v1）

实机尚未完成时，前端按本文档保留字段和接口。机器人完成后，仅需要实现其中一种数据接入方式：HTTP API 或浏览器注入的 `window.ROBOT_DATA_ADAPTER`。

## 1. HTTP 接口

开发环境可由 `frontend/public/runtime-config.js` 或地址参数指定接口前缀；统一部署时，背屏通过同一 8000 服务自动使用 `${window.location.origin}/api/v1`。

| 用途 | 方法与路径 |
| --- | --- |
| 实时快照 | `GET /robot/snapshot` |
| 当前告警 | `GET /alarms` |
| 本次作业总结 | `GET /work-summary` |
| 一键诊断 | `POST /commands/diagnose` |
| 底盘软件急停 | `POST /commands/soft-stop` |
| 底盘复位 | `POST /commands/chassis-reset` |
| 确认恢复告警 | `POST /alarms/:id/acknowledge` |
| 清除已恢复告警 | `POST /alarms/clear-recovered` |

所有成功命令至少返回：`{ "accepted": true, "commandId": "..." }`。`accepted` 仅表示请求已受理；实际安全动作和最终状态必须由下一次快照/告警结果确认。

底盘软件急停使用 `ROS_STOP_SERVICE` 指定的 `std_srvs/srv/Trigger` 服务，默认 `/zj_humanoid/chassis/soft_estop`。当前页面不提供软件急停按钮。

复位状态由后端从 AGVNewState 反馈派生，无需外部 `controlState` 话题。快照的 `controlState` 为四种状态之一，未收到反馈时为空。`chassisReset` 包含 `resetAllowed`、`blockReason`、`error`、`feedbackFresh`、`motionInterlockReady`，前端根据这些字段开放或禁用按钮，并保留二次确认。

复位由本项目的 `robot-motion-supervisor` 执行。HTTP 后端调用我们自己的 `/{ROBOT_NAME}/back_screen/reset`（Trigger），主控完成运动门控、导航目标取消及任务中断记录后，才调用底盘 `agv_reset`。界面受理不代表底盘已复位，最终结果看后续快照。

`ROS_ENABLE_RESET` 独立控制人工复位权限；`ROS_ENABLE_CONTROL` 仍用于原有软件停止接口。完整流程、三路底盘运动出口、复位后新任务确认及现场验收方法见 [急停复位实现](backend/CHASSIS_RESET.md)。

## 2. 实时快照

`GET /robot/snapshot` 每秒提供一次最新状态。可直接返回对象，也可包在 `{ "data": { ... } }` 中。

```json
{
  "robotModel": "R1",
  "health": { "level": "normal", "label": "系统健康", "alertCount": 0 },
  "motion": {
    "position": "X1.23 Y2.34 Z0.56",
    "target": "X5.00 Y3.00 Z1.20",
    "speed": "0.45 m/s",
    "leftTcp": "X1.23 Y2.62 Z0.56",
    "rightTcp": "X1.23 Y2.06 Z0.56",
    "joints": [15, 23, -8, 42, 11, 5],
    "jointPositions": {
      "Shoulder_X_L": 1.35,
      "Shoulder_X_R": -1.35
    }
  },
  "payloadKg": 2.3,
  "gripForceN": 12.5,
  "operationMode": "自动",
  "uptime": "2h23m",
  "battery": {
    "percent": 85,
    "remainingMinutes": 42,
    "voltage": 14.8,
    "current": 3.2,
    "temperature": 28,
    "cellVoltage": 3.7,
    "chargeStatus": "充电中",
    "cycles": 12
  },
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

`health.level` 只能是 `normal`、`info`、`warning`、`critical`、`emergency`。`remainingMinutes` 由实机侧按当前电量与最近 20 次平均耗电计算；前端不自行推算。

`motion.leftTcp`、`motion.rightTcp` 分别是左、右手末端工具中心点（TCP）的 XYZ 坐标。双臂机器人必须分别提供；旧字段 `motion.tcp` 只为旧版调用方兼容保留，新页面不再显示它。

`motion.jointPositions` 用于 3D 视图：键为 URDF 关节名，值为 ROS2 原始弧度值（直线关节为米）。收到该字段后，模型会实时跟随实机姿态；字段不存在时模型保持演示姿态。

`sensors.bumper` 为碰撞条三态：`online`（绿色，在线未碰撞）、`triggered`（黄色，已碰撞）、`offline`（红色，不在线）。为兼容旧适配器，布尔值 `true` 等同 `online`，`false` 等同 `offline`。

## 3. 告警与作业数据

告警项至少包含 `id`、`code`、`severity`、`title`、`time`、`desc`、`suggestion`。`severity` 使用 `info`、`warning`、`critical`、`emergency`。

作业总结至少包含上次结束充电电量、触发时电量、充电时间戳、额定负载和 `tasks`；每个任务含名称、重量和时间。

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
