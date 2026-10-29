"""背屏数据服务入口：只负责接收请求并调用背屏业务逻辑。"""

from __future__ import annotations

import os
from pathlib import Path
from contextlib import asynccontextmanager
from typing import Any, Dict

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from robot_back_screen.clients.diagnosis_engine import create_diagnosis_engine
from robot_back_screen.monitor_page import MONITOR_HTML
from robot_back_screen.services.unified_service import UnifiedDiagnosticsService


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.service = UnifiedDiagnosticsService(create_diagnosis_engine())
    yield


app = FastAPI(
    title="机器人背屏数据服务",
    description=(
        "背屏后端的接口说明与单次测试台。可在此查看服务状态、验证机器人数据，并测试诊断与告警操作。\n\n"
        "需要持续查看数据变化时，请打开 [实时监控页（/monitor）](/monitor)。"
    ),
    version="0.1.0",
    lifespan=lifespan,
    openapi_tags=[
        {"name": "服务状态", "description": "先在这里确认后端是否运行，以及是否已收到真实 ROS 数据。"},
        {"name": "背屏实时数据", "description": "背屏状态、告警和作业总结所读取的数据。"},
        {"name": "诊断与控制", "description": "从背屏发出的诊断或停止请求。实机控制需满足安全权限。"},
        {"name": "告警处理", "description": "在故障恢复后确认或清除告警。"},
    ],
)
origins = [origin.strip() for origin in os.getenv("CORS_ORIGINS", "http://127.0.0.1:5173,http://localhost:5173,http://127.0.0.1:5174,http://localhost:5174").split(",") if origin.strip()]
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["*"], allow_headers=["*"], allow_credentials=True)


def frontend_directory() -> Path | None:
    """Locate compiled web files in development or after ROS installation."""
    configured = os.getenv("BACK_SCREEN_WEB_DIR")
    candidates = [Path(configured)] if configured else []
    candidates.append(Path(__file__).resolve().parents[1] / "frontend" / "dist")
    try:
        from ament_index_python.packages import get_package_share_directory
        candidates.append(Path(get_package_share_directory("robot_back_screen")) / "web")
    except (ImportError, LookupError):
        # Allows local Python development before the ROS2 package is installed.
        pass
    return next((directory for directory in candidates if directory.is_dir() and (directory / "index.html").is_file()), None)


WEB_DIRECTORY = frontend_directory()
if WEB_DIRECTORY:
    app.mount("/assets", StaticFiles(directory=WEB_DIRECTORY / "assets"), name="back-screen-assets")
    app.mount("/models", StaticFiles(directory=WEB_DIRECTORY / "models"), name="back-screen-models")


@app.get("/", include_in_schema=False)
async def back_screen() -> FileResponse:
    """Production page, delivered by the same service as its API."""
    if not WEB_DIRECTORY:
        raise RuntimeError("未找到背屏前端构建文件；请先在 frontend 目录执行 npm run build。")
    return FileResponse(WEB_DIRECTORY / "index.html", headers={"Cache-Control": "no-store"})


@app.get("/runtime-config.js", include_in_schema=False)
async def runtime_config() -> FileResponse:
    """Deployment-time browser configuration, kept outside the Vite bundle."""
    if not WEB_DIRECTORY:
        raise RuntimeError("未找到背屏前端构建文件；请先在 frontend 目录执行 npm run build。")
    return FileResponse(WEB_DIRECTORY / "runtime-config.js", media_type="application/javascript", headers={"Cache-Control": "no-store"})


def service() -> UnifiedDiagnosticsService:
    return app.state.service


@app.get("/monitor", include_in_schema=False, response_class=HTMLResponse)
async def monitor() -> str:
    """供联调人员查看的只读实时监控页；Swagger /docs 仍用于单次接口测试。"""
    return HTMLResponse(MONITOR_HTML, headers={"Cache-Control": "no-store, no-cache, must-revalidate"})


@app.get("/healthz", summary="检查服务与实机数据状态", tags=["服务状态"])
async def healthz() -> Dict[str, Any]:
    diagnosis_mode = (
        "诊断引擎适配器" if os.getenv("DIAGNOSIS_WS_URL")
        else "内置实时诊断"
    )
    return {
        "status": "ok",
        "diagnosisMode": diagnosis_mode,
        **(await service().telemetry_status()),
    }


@app.get("/api/v1/robot/snapshot", summary="读取机器人实时状态", tags=["背屏实时数据"])
async def robot_snapshot() -> Dict[str, Any]:
    return await service().snapshot()


@app.get("/api/v1/alarms", summary="读取当前告警", tags=["背屏实时数据"])
async def alarms() -> Dict[str, Any]:
    return {"data": await service().alarms()}


@app.get("/api/v1/work-summary", summary="读取本次作业总结", tags=["背屏实时数据"])
async def work_summary() -> Dict[str, Any]:
    return await service().work_summary()


@app.get("/api/v1/history", summary="读取真实运行日志", tags=["背屏实时数据"])
async def history() -> Dict[str, Any]:
    return {"data": await service().logs()}


@app.post("/api/v1/commands/diagnose", summary="执行一次诊断", tags=["诊断与控制"])
async def diagnose() -> Dict[str, Any]:
    return await service().diagnose()


@app.post("/api/v1/commands/soft-stop", summary="请求软件停止", tags=["诊断与控制"])
async def soft_stop() -> Dict[str, Any]:
    return await _control_request(service().soft_stop())


@app.post("/api/v1/commands/chassis-reset", summary="请求底盘复位", tags=["诊断与控制"])
async def chassis_reset() -> Dict[str, Any]:
    return await _control_request(service().reset_chassis())


async def _control_request(action: Any) -> Dict[str, Any]:
    try:
        return await action
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except TimeoutError as exc:
        raise HTTPException(status_code=504, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/api/v1/alarms/{alarm_id}/acknowledge", summary="确认单条已恢复告警", tags=["告警处理"])
async def acknowledge_alarm(alarm_id: str) -> Dict[str, Any]:
    return await service().recover_alarm(alarm_id)


@app.post("/api/v1/alarms/clear-recovered", summary="清除全部已恢复告警", tags=["告警处理"])
async def clear_recovered() -> Dict[str, Any]:
    return await service().clear_recovered()


def run() -> None:
    """Console entry point used by the ROS2 package and systemd service."""
    import uvicorn

    uvicorn.run(
        "robot_back_screen.main:app",
        host=os.getenv("BACK_SCREEN_HOST", "127.0.0.1"),
        port=int(os.getenv("BACK_SCREEN_PORT", "8000")),
    )
