# 背屏后端小白指南

这不是一个网站，而是运行在机器人本机上的“小翻译员”。背屏网页不直接理解 ROS 话题；它只向本服务要一份整理好的状态数据。

```text
机器人或模拟数据
        ↓
本服务整理数据
        ↓
背屏网页显示
```

## 只需要认识三个代码文件

| 先后顺序 | 文件 | 作用 |
| --- | --- | --- |
| 1 | `app/main.py` | 对外开哪些门。背屏通过这些地址要数据或发操作。 |
| 2 | `app/services/unified_service.py` | 把“数据”和“告警”组合成背屏能直接显示的一份结果。 |
| 3 | `app/services/telemetry.py` | 数据从哪里来：现在是模拟数据，以后是 ROS 数据。 |

`app/clients/diagnosis_engine.py` 是未来连接自定义规则引擎的预留文件；当前背屏开发不需要阅读它。

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

## 两种运行模式

### 模拟模式（现在使用）

```text
telemetry.py 自己生成电量、位置、温度等演示数据
```

没有机器人也能开发背屏。运行后端时不设置任何额外配置，默认就是此模式。

### ROS 模式（接实机时使用）

```text
telemetry.py 订阅真实机器人的 ROS 话题
```

需要在机器人环境设置：

```bash
source /etc/nav01/robot/robot_env.sh
export TELEMETRY_MODE=ros
```

之后后端会从真实接口读取电池、位置、速度、关节、诊断汇总等数据。详情见 [ROS 主分支接口映射](ROS_MAIN_FIELD_MAPPING.md)。

## 你当前需要做什么

现在只需要启动后端和背屏，确认背屏右上角显示“后端数据”。

实机准备好后，先运行：

```bash
echo $ROBOT_NAME
ros2 topic list
```

再按 ROS 映射文档逐项确认接口。不要在不清楚安全状态时开启真实急停控制。
