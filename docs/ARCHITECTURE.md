# 背屏工程结构

更新日期：2026-11-11。实际操作见 [背屏使用说明](背屏交付与使用手册.md)，各项数据来源见 [topic 对照](backend/ROS_MAIN_FIELD_MAPPING.md)。

```text
robot_back_screen/      Python 后端：ROS2 订阅、数据合并、HTTP API
frontend/index.html     页面结构与资源入口
frontend/src/styles/    工业屏视觉样式
frontend/src/scripts/   页面状态、交互、渲染和图表逻辑
frontend/src/three/     3D 模型加载与关节姿态显示
frontend/src/api/       前端 API 契约与请求适配层
frontend/public/        运行时配置和 3D 模型资源
launch/                 ROS2 启动入口
deploy/                 构建、systemd、Pico 屏幕启动脚本
docs/                   架构和接入说明
```

开发时 Vite 提供前端服务器；生产时前端构建产物由 `robot_back_screen/main.py` 的同一个 8000 服务提供。现有内联事件在 `frontend/src/scripts/app.js` 内继续以全局函数运行，避免迁移时破坏触摸操作；后续新增功能应按数据、接口、视图三层拆分，不再继续向页面结构文件堆叠逻辑。

Pico 安装两个服务：`robot-back-screen-api` 负责订阅与网页/API，`robot-back-screen-kiosk` 负责全屏浏览器。Orin 的 `robot-motion-supervisor` 负责复位主控和底盘运动门控。`deploy/install.sh pico|orin` 安装并启用对应的开机自启动；`deploy/start.sh pico|orin` 手动启动已安装服务。

Pico 通过 ROS2 网络读取 Orin 数据；`clients/remote_robot.py` 仅在配置 `ORIN_API_BASE` 时请求已有 Orin HTTP 后端。默认部署不要求 Orin 运行第二个背屏 HTTP 服务。
