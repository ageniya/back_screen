# 背屏机器人数据接口契约（v1）

实机尚未完成时，前端按本文档保留字段和接口。机器人完成后，仅需要实现其中一种数据接入方式：HTTP API 或浏览器注入的 `window.ROBOT_DATA_ADAPTER`。

## 1. HTTP 接口

接口前缀由部署配置 `public/runtime-config.js` 中的 `window.ROBOT_DIAGNOSTIC_API` 指定，例如 `http://127.0.0.1:8080/api/v1`。

| 用途 | 方法与路径 |
| --- | --- |
| 实时快照 | `GET /robot/snapshot` |
| 当前告警 | `GET /alarms` |
| 本次作业总结 | `GET /work-summary` |
| 一键诊断 | `POST /commands/diagnose` |
| 急停（软件停止） | `POST /commands/soft-stop` |
| 确认恢复告警 | `POST /alarms/:id/acknowledge` |
| 清除已恢复告警 | `POST /alarms/clear-recovered` |

所有成功命令至少返回：`{ "accepted": true, "commandId": "..." }`。`accepted` 仅表示请求已受理；实际安全动作和最终状态必须由下一次快照/告警结果确认。

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
    "tcp": "X1.23 Y2.34",
    "joints": [15, 23, -8, 42, 11, 5]
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
