# 背屏后端使用速查

更新日期：2026-11-11。完整启动、关闭和页面操作见 [使用说明](../背屏交付与使用手册.md)，每项数据的 topic 和消息类型见 [数据来源对照](ROS_MAIN_FIELD_MAPPING.md)。

## 后端做什么

Pico 后端订阅 Pico / Orin 的 ROS2 话题，把运动、电池、计算资源、相机等状态整理为 HTTP 数据，同时托管网页。缺少有效消息的字段显示 `--`。

状态页点击复位后，由 Pico 后端请求 Orin 的复位主控，再由主控处理旧任务、运动门控和底盘复位。具体链路见 [复位说明](CHASSIS_RESET.md)。网页没有软件急停按钮。

## 安装和启动

项目中已有构建好的 `frontend/dist/` 后，在 Pico 的项目根目录首次执行：

```bash
bash deploy/install.sh pico
```

安装后开启前后端用 `bash deploy/start.sh pico`。只关闭网页用 `sudo systemctl stop robot-back-screen-kiosk.service`；重开用 `sudo systemctl start robot-back-screen-kiosk.service`。后端安装配置为 `/etc/robot-back-screen/env`。

## 在哪里看数据

Pico 本机使用 `http://127.0.0.1:8000/`。监控页为 `/monitor`，每 5 秒刷新，可分别选择 Orin / Pico；`/docs` 展示 HTTP 接口及单次请求结果，不会自动重复请求。

| 功能 | HTTP 接口 |
| --- | --- |
| 后端和 ROS 数据接收状态 | `GET /healthz` |
| 状态页数据 | `GET /api/v1/robot/snapshot` |
| 具体告警列表 | `GET /api/v1/alarms` |
| 日志 | `GET /api/v1/history` |
| 作业总结 | `GET /api/v1/work-summary`，当前本地无完整作业数据源时返回空记录 |
| 刷新诊断 | `POST /api/v1/commands/diagnose`，默认基于已读取数据检查 |
| 底盘复位请求 | `POST /api/v1/commands/chassis-reset`，必须由操作者确认后触发 |
| 确认单条告警已恢复 | `POST /api/v1/alarms/{id}/acknowledge` |
| 确认已恢复告警 | `POST /api/v1/alarms/clear-recovered` |

通用 `ROS-1/2/3` 诊断项不显示在用户告警中。CPU 等具体资源告警和数据离线告警继续保留，默认持续 5 秒才显示。

## 需要看代码时

| 文件 | 功能 |
| --- | --- |
| `robot_back_screen/main.py` | HTTP API 与前端静态文件入口 |
| `robot_back_screen/services/telemetry.py` | ROS2 订阅、字段转换与数据新鲜度处理 |
| `robot_back_screen/services/unified_service.py` | 状态整理、具体告警规则和可选 Orin HTTP 合并 |
| `robot_back_screen/services/runtime_metrics.py` | 由电池读数推断充电状态和计算续航 |
| `robot_back_screen/motion_supervisor.py` | Orin 上的复位主控和运动门控 |
| `robot_back_screen/monitor_page.py` | 只读监控网页 |

当前使用真实 ROS 数据模式 `TELEMETRY_MODE=ros`。`DIAGNOSIS_WS_URL` 留空即使用内置实时诊断，不需要单独部署诊断引擎。
