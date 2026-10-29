# 机器人背屏（统一交付包）

这是随机器人中间件一起交付的 ROS2 软件包。它把三件事放进同一次版本管理和 `.deb` 升级中：

```text
ROS2 真实话题
    ↓
robot_back_screen/        Python 后端：订阅、整理、诊断、HTTP API
    ↓ 同一服务
frontend/                 背屏网页：状态、告警、日志、作业总结、3D 视图
```

Pico 运行 API/网页服务和全屏浏览器两个 systemd 服务；Orin 运行底盘复位主控服务。API 同时提供 `/api/v1/...` 和 `/`，机器人上不需要 `npm run dev` 或 5173 端口。

## 目录

| 目录 | 用途 |
| --- | --- |
| `robot_back_screen/` | Python 后端主体，订阅 Pico/Orin ROS2 话题并提供 API。 |
| `frontend/` | 前端源码；仅开发与构建时需要 Node.js。 |
| `docs/` | API 契约、架构和 ROS 字段映射。 |
| `launch/` | ROS2 启动入口。 |
| `deploy/` | systemd、构建和 Pico 屏幕启动示例。 |
| `package.xml`、`setup.py` | ROS2/ament 打包定义。 |

### 文件用途速查

以下路径相对于 `robot-back-screen/`，并非每个文件都会在运行时直接加载：

| 路径 | 用途 |
| --- | --- |
| `robot_back_screen/main.py` | 后端入口、HTTP 接口和网页服务。 |
| `robot_back_screen/services/telemetry.py` | 订阅 ROS2 话题并整理机器人状态。 |
| `robot_back_screen/services/unified_service.py` | 合并数据并提供诊断、告警等服务。 |
| `robot_back_screen/services/runtime_metrics.py` | 电池状态、运行时长和续航相关计算。 |
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
| `ros2_media_play/`、`deploy/zj-media-play.service` | 独立的视频播放 ROS2 包及其服务，并非背屏页面本身。 |

本机的 `.venv/`、`frontend/node_modules/` 和 `frontend/dist/` 是生成的依赖或构建产物，不提交到 Git；其中 `dist/` 用于后端托管已构建的页面及打包交付，需要时可通过 `npm run build` 重新生成。

## 本机开发

前端：

```bash
cd frontend
npm install
npm run dev
```

后端：

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

开发电脑先构建网页，再将**整个仓库（包含 `frontend/dist/`）**复制到对应机器人。部署脚本从源码树安装，暂不替代中间件 `.deb` 的制作流程。

```bash
cd frontend && npm ci && npm run build && cd ..
# Pico 上执行：安装 API、网页、全屏显示，启用两个开机自启服务
bash deploy/install.sh pico
# Orin 上执行：确认底盘静止、备份并安装运动门控与复位主控，启用开机自启
bash deploy/install.sh orin
```

Pico 和 Orin 分别只执行自己的命令。安装后需要手动启动时运行 `bash deploy/start.sh pico` 或 `bash deploy/start.sh orin`。查看状态：Pico 用 `systemctl status robot-back-screen-api robot-back-screen-kiosk`；Orin 用 `systemctl status robot-motion-supervisor`。Pico 页面为 `http://127.0.0.1:8000/`。

Pico 配置在 `/etc/robot-back-screen/env`，首次安装写入真实 ROS 话题和两机地址；Orin 配置在 `/etc/robot-back-screen-motion/env`。安装脚本会保留现有 Pico 配置，不覆盖现场修改。Orin 安装会短暂重启实际底盘 ROS 服务并保持运动门控锁定，**不自动调用复位**。有关人工复位及新任务确认，见 [急停复位实现](docs/backend/CHASSIS_RESET.md)。

制作 `.deb` 时应把这两个安装入口和配置、systemd unit 一起纳入交付；`deploy/build_deb.sh` 目前仅生成 ROS 工作空间构建结果，不会产出 `.deb`。首次安装 Python 依赖需要可用的软件源或预备的离线 wheel 包。

## 相关文档

- [系统结构](docs/ARCHITECTURE.md)
- [背屏交付与使用手册](docs/背屏交付与使用手册.md)
- [视频包交付测试](docs/视频包交付测试.md)
- [前后端接口契约](docs/ROBOT_API_CONTRACT.md)
- [后端小白指南](docs/backend/BACKEND_GUIDE.md)
- [ROS 主分支字段映射](docs/backend/ROS_MAIN_FIELD_MAPPING.md)

急停复位的部署与验收见 [急停复位实现](docs/backend/CHASSIS_RESET.md)。
