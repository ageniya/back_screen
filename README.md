# 机器人背屏（统一交付包）

这是随机器人中间件一起交付的 ROS2 软件包。它把三件事放进同一次版本管理和 `.deb` 升级中：

```text
ROS2 真实话题
    ↓
robot_back_screen/        Python 后端：订阅、整理、诊断、HTTP API
    ↓ 同一服务
frontend/                 背屏网页：状态、告警、日志、作业总结、3D 视图
```

生产环境只需启动 **一个服务**：`robot-back-screen-api`。它既提供 API（`/api/v1/...`），也提供背屏页面（`/`）；不再需要在机器人上运行 `npm run dev` 或额外的 5173 端口。

## 目录

| 目录 | 用途 |
| --- | --- |
| `robot_back_screen/` | Python 后端主体，订阅 Pico/Orin ROS2 话题并提供 API。 |
| `frontend/` | 前端源码；仅开发与构建时需要 Node.js。 |
| `docs/` | API 契约、架构和 ROS 字段映射。 |
| `launch/` | ROS2 启动入口。 |
| `deploy/` | systemd、构建和 Pico 屏幕启动示例。 |
| `package.xml`、`setup.py` | ROS2/ament 打包定义。 |

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

## 机器人交付

1. 将本仓库放入机器人中间件工作空间的 `src/robot_back_screen`。
2. 在 `frontend/` 执行 `npm ci && npm run build`，生成发布网页。
3. 在工作空间执行 `colcon build --packages-select robot_back_screen`，再由中间件发布流程制作 `.deb`。
4. 机器人安装 `.deb` 后，以 `ros2 launch robot_back_screen back_screen.launch.py` 或 systemd 启动。
5. Pico 浏览器打开 `http://127.0.0.1:8000/`。

实机必须在启动服务前加载对应机器人的 ROS2 环境，并在 `/etc/robot-back-screen/env` 配置 `TELEMETRY_MODE=ros`、Orin 地址等变量。示例见 [.env.example](.env.example)。

> 急停属于安全功能。当前后端默认 `ROS_ENABLE_CONTROL=false`，不会因网页点击而直接控制实机；任何开放控制的改动都必须走安全评审。

## 相关文档

- [系统结构](docs/ARCHITECTURE.md)
- [背屏交付与使用手册](docs/背屏交付与使用手册.md)
- [视频包交付测试](docs/视频包交付测试.md)
- [前后端接口契约](docs/ROBOT_API_CONTRACT.md)
- [后端小白指南](docs/backend/BACKEND_GUIDE.md)
- [ROS 主分支字段映射](docs/backend/ROS_MAIN_FIELD_MAPPING.md)
