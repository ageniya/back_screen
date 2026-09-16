# 背屏工程结构

```text
index.html              页面结构与资源入口
src/styles/app.css      工业屏视觉样式
src/scripts/app.js      页面状态、交互、渲染和图表逻辑
src/data/               演示数据与默认配置（逐步迁移）
src/api/                实机数据/命令适配层（逐步接入）
public/runtime-config.js 部署时配置实机 API 地址
docs/                   架构和接入说明
```

当前保持无框架运行时和最小依赖，使用 Vite 提供开发服务器和生产构建。现有内联事件在 `app.js` 内继续以全局函数运行，避免迁移时破坏触摸操作；后续新增功能应按数据、接口、视图三层拆分，不再继续向页面结构文件堆叠逻辑。
