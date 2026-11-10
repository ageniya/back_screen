# 机器人背屏

更新日期：2026-11-11。项目包含背屏前端、ROS2 数据后端和急停复位主控，使用同一份代码管理：

```text
ROS2 真实话题
    ↓
robot_back_screen/        Python 后端：订阅、整理、诊断、HTTP API
    ↓ 同一服务
frontend/                 背屏网页：状态、告警、日志、作业总结、3D 视图
```

Pico 运行 API/网页服务和全屏浏览器两个 systemd 服务；Orin 运行底盘复位主控服务。API 同时提供 `/api/v1/...` 和 `/`，机器人上不需要 `npm run dev` 或 5173 端口。

先阅读 [背屏使用说明](docs/背屏交付与使用手册.md)；每项数据的 topic、消息类型和计算来源见 [数据与 topic 对照](docs/backend/ROS_MAIN_FIELD_MAPPING.md)。接手代码时可阅读 [核心文件说明](docs/核心文件说明.md)，了解重要文件的作用及常见修改入口。

代码仓库：内网 [wangyulong/back_screen](http://10.51.33.13/wangyulong/back_screen)，GitHub [ageniya/back_screen](https://github.com/ageniya/back_screen)（私有），分支均为 `main`。文档描述仓库实现，具体机器人是否已部署新版需查看该机文件和服务。

## 目录

| 目录 | 用途 |
| --- | --- |
| `robot_back_screen/` | Python 后端主体，订阅 Pico/Orin ROS2 话题并提供 API。 |
| `frontend/` | 前端源码；仅开发与构建时需要 Node.js。 |
| `docs/` | API 契约、架构和 ROS 字段映射。 |
| `launch/` | ROS2 启动入口。 |
| `deploy/` | 部署、手动启动、systemd 和屏幕启动脚本。 |
| `package.xml`、`setup.py` | ROS2/ament 打包定义。 |

### 文件用途速查

以下路径相对于 `robot-back-screen/`，并非每个文件都会在运行时直接加载：

| 路径 | 用途 |
| --- | --- |
| `robot_back_screen/main.py` | 后端入口、HTTP 接口和网页服务。 |
| `robot_back_screen/services/telemetry.py` | 订阅 ROS2 话题并整理机器人状态。 |
| `robot_back_screen/services/unified_service.py` | 合并数据并提供诊断、告警等服务。 |
| `robot_back_screen/services/runtime_metrics.py` | 电池充电状态推断和续航计算；开机时长由 `telemetry.py` 读取。 |
| `robot_back_screen/clients/remote_robot.py` | 请求另一台机器人计算机上的后端数据。 |
| `robot_back_screen/clients/diagnosis_engine.py` | 可选的外部诊断引擎适配。 |
| `robot_back_screen/motion_supervisor.py` | 复位主控：底盘运动门控、导航目标取消、状态反馈与超时。 |
| `robot_back_screen/services/chassis_reset.py`、`motion_gate.py` | 急停复位状态机和运动/任务锁定逻辑。 |
| `robot_back_screen/monitor_page.py` | 后端实时监控页面。 |
| `frontend/index.html`、`frontend/src/` | 页面结构、交互、样式、数据适配和 3D 查看器。 |
| `frontend/public/models/` | 3D 模型的 URDF 和网格资源。 |
| `frontend/public/runtime-config.js` | 前端运行配置。 |
| `launch/`、`deploy/`、`resource/` | ROS 启动、服务、构建和安装所需文件。 |
| `package.xml`、`setup.py`、`setup.cfg`、`requirements.txt` | 后端依赖与 ROS2 打包配置。 |
| `frontend/package.json`、`frontend/package-lock.json` | 前端依赖和构建配置。 |
| `.env.example` | 后端配置示例；实际环境配置另行提供。 |
| `tests/` | 本地自动测试，不属于运行中的页面。 |
| `docs/` | 架构、接口、部署和测试说明。 |

本机的 `.venv/`、`frontend/node_modules/` 和 `frontend/dist/` 是生成的依赖或构建产物，不提交到 Git；其中 `dist/` 用于后端托管已构建的页面及打包交付，需要时可通过 `npm run build` 重新生成。

仓库仅保留背屏所需源码、3D 模型、部署脚本、使用文档和维护测试。Python 安装范围限定为 `robot_back_screen` 及其子模块。清理后首次开发需重新安装依赖并构建前端；直接拉取仓库不会带上 `.venv/`、`node_modules/` 或 `dist/`。

## 本机开发

前端（开发电脑先准备 Node.js 22）：

```bash
cd frontend
npm ci
npm run dev
```

后端（需在已加载 ROS2 及消息包的环境中运行，仅支持真实 ROS 数据模式）：

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn robot_back_screen.main:app --host 127.0.0.1 --port 8000 --reload
```

开发联调时打开：

```text
http://127.0.0.1:5173/?api=http://127.0.0.1:8000/api/v1
```

后端接口说明：`http://127.0.0.1:8000/docs`；自动刷新的真实数据页：`http://127.0.0.1:8000/monitor`。

## 一键部署与启动

开发电脑先构建网页，再将项目及 `frontend/dist/` 复制到对应机器人。以下命令从项目根目录执行：

```bash
nvm use 22
npm --prefix frontend ci
npm --prefix frontend run build
# Pico 上执行：安装 API、网页、全屏显示，启用两个开机自启服务
bash deploy/install.sh pico
# Orin 上执行：确认底盘静止、备份并安装运动门控与复位主控，启用开机自启
bash deploy/install.sh orin
```

安装后手动启动用 `bash deploy/start.sh pico` 或 `bash deploy/start.sh orin`；脚本启动已安装的 systemd 服务，不负责启动整套机器人中间件。Pico 页面为 `http://127.0.0.1:8000/`。

| 常用操作 | 命令 |
| --- | --- |
| Pico 仅关闭显示界面 | `sudo systemctl stop robot-back-screen-kiosk.service` |
| Pico 重新打开显示界面 | `sudo systemctl start robot-back-screen-kiosk.service` |
| Pico 重启前后端 | `sudo systemctl restart robot-back-screen-api.service robot-back-screen-kiosk.service` |
| Pico 查看自启动 | `systemctl is-enabled robot-back-screen-api.service robot-back-screen-kiosk.service` |
| Orin 查看主控状态 | `systemctl status robot-motion-supervisor.service` |

安装脚本会启用开机自启动。Pico 在已有 GDM 配置时设置 `nav01` 自动登录，屏幕启动脚本关闭 GNOME 自动锁屏和 X11 屏保；当前显示配置按 GNOME/GDM、X11、`DISPLAY=:1`、UID 1000 编写。运行中的浏览器关闭后可能被 systemd 再次拉起，需要保持关闭时使用上表的 `stop`。

Pico 配置在 `/etc/robot-back-screen/env`，首次安装写入真实 ROS 话题和两机地址；Orin 配置在 `/etc/robot-back-screen-motion/env`。安装脚本会保留现有 Pico 配置，不覆盖现场修改。Orin 安装会短暂重启实际底盘 ROS 服务并保持运动门控锁定，**不自动调用复位**。有关人工复位及新任务确认，见 [急停复位实现](docs/backend/CHASSIS_RESET.md)。

首次安装 Python 依赖需要可用的软件源或事先准备的离线依赖。Pico 可直接通过 ROS2 订阅 Orin 数据；`ORIN_API_BASE` 仅在已有独立 Orin HTTP 后端时配置。`ORIN_IP` 用于显示地址，不表示需要启动第二个 HTTP 后端。

在自己电脑查看时，可用 `ssh -N -L 18000:127.0.0.1:8000 nav01@PICO_IP` 转发后打开 `http://127.0.0.1:18000/`，将 `PICO_IP` 替换为当前地址。

## 相关文档

- [系统结构](docs/ARCHITECTURE.md)
- [核心文件说明](docs/核心文件说明.md)
- [背屏交付与使用手册](docs/背屏交付与使用手册.md)
- [前后端接口契约](docs/ROBOT_API_CONTRACT.md)
- [后端小白指南](docs/backend/BACKEND_GUIDE.md)
- [ROS 主分支字段映射](docs/backend/ROS_MAIN_FIELD_MAPPING.md)

复位按钮的状态条件、调用链路和使用方法见 [急停复位说明](docs/backend/CHASSIS_RESET.md)。
