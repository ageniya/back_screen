# 背屏后端小白指南

这不是一个网站，而是运行在机器人本机上的“小翻译员”。背屏网页不直接理解 ROS 话题；它只向本服务要一份整理好的状态数据。

```text
机器人 ROS2 数据
        ↓
本服务整理数据
        ↓
背屏网页显示
```

## 只需要认识三个代码文件

| 先后顺序 | 文件 | 作用 |
| --- | --- | --- |
| 1 | `robot_back_screen/main.py` | 对外开哪些门。背屏通过这些地址要数据或发操作。 |
| 2 | `robot_back_screen/services/unified_service.py` | 把“数据”和“告警”组合成背屏能直接显示的一份结果。 |
| 3 | `robot_back_screen/services/telemetry.py` | 订阅 ROS2 话题，转换为背屏数据。 |

`robot_back_screen/clients/diagnosis_engine.py` 是未来连接自定义规则引擎的预留文件；当前背屏开发不需要阅读它。

## 背屏实际使用的接口

| 背屏动作 | 后端接口 | 含义 |
| --- | --- | --- |
| 打开状态页 | `GET /api/v1/robot/snapshot` | 取一次机器人完整状态。 |
| 打开告警页 | `GET /api/v1/alarms` | 取当前告警列表。 |
| 打开作业总结 | `GET /api/v1/work-summary` | 取本次作业统计。 |
| 点击一键诊断 | `POST /api/v1/commands/diagnose` | 请求诊断引擎执行检查。 |
| 点击急停 | `POST /api/v1/commands/soft-stop` | 请求软件停止；实机默认禁止控制，需额外开启。 |
| 确认告警恢复 | `POST /api/v1/alarms/{id}/acknowledge` | 确认一条已恢复告警。 |
| 清除已恢复告警 | `POST /api/v1/alarms/clear-recovered` | 请求清理恢复状态的告警。 |

## ROS 数据模式

后端订阅真实机器人的 ROS2 话题。请在运行后端的机器上加载对应中间件环境，并设置 `TELEMETRY_MODE=ros`。例如 Pico 上：

```bash
source /etc/nav01/Middleware.env
export TELEMETRY_MODE=ros
```

缺少消息包或话题没有发布者时，对应数据不可用。详情见 [ROS 主分支接口映射](ROS_MAIN_FIELD_MAPPING.md)。

## 你当前需要做什么

现在只需要启动后端和背屏，查看背屏右上角的连接状态，确认已收到 ROS 数据。

实机准备好后，先运行：

```bash
echo $ROBOT_NAME
ros2 topic list
```

再按 ROS 映射文档逐项确认接口。不要在不清楚安全状态时开启真实急停控制。
