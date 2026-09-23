# 背屏工程结构

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
