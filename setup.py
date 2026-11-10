"""ROS2/ament packaging entry for the unified robot back-screen."""

from __future__ import annotations

from pathlib import Path

from setuptools import find_packages, setup


PACKAGE_NAME = "robot_back_screen"
ROOT = Path(__file__).parent
WEB_ROOT = ROOT / "frontend" / "dist"


def web_data_files() -> list[tuple[str, list[str]]]:
    """Install the already-built frontend alongside this ROS package."""
    if not WEB_ROOT.is_dir():
        return []
    grouped: dict[str, list[str]] = {}
    for path in WEB_ROOT.rglob("*"):
        if path.is_file():
            target = f"share/{PACKAGE_NAME}/web/{path.parent.relative_to(WEB_ROOT)}"
            grouped.setdefault(target, []).append(str(path))
    return list(grouped.items())


setup(
    name=PACKAGE_NAME,
    version="0.1.0",
    packages=find_packages(include=[PACKAGE_NAME, f"{PACKAGE_NAME}.*"]),
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/robot_back_screen"]),
        (f"share/{PACKAGE_NAME}", ["package.xml", "requirements.txt"]),
        (f"share/{PACKAGE_NAME}/launch", ["launch/back_screen.launch.py"]),
        (f"share/{PACKAGE_NAME}/deploy", [
            "deploy/install.sh", "deploy/install-pico.sh", "deploy/start.sh",
            "deploy/start-pico-api.sh", "deploy/start-pico-screen.sh",
            "deploy/start-motion-supervisor.sh", "deploy/install-motion-supervisor.sh",
            "deploy/robot-back-screen-api.service", "deploy/robot-back-screen-kiosk.service",
            "deploy/robot-motion-supervisor.service", "deploy/build-chassis-interface.sh",
        ]),
    ] + web_data_files(),
    install_requires=["setuptools", "fastapi>=0.115,<1.0", "uvicorn[standard]>=0.30,<1.0", "websockets>=13,<16"],
    scripts=["deploy/start-pico-screen.sh"],
    zip_safe=False,
    maintainer="机器人软件组",
    maintainer_email="robot@example.invalid",
    description="机器人背屏 ROS2 数据服务与显示页面",
    license="Proprietary",
    entry_points={"console_scripts": [
        "robot-back-screen-api = robot_back_screen.main:run",
        "robot-motion-supervisor = robot_back_screen.motion_supervisor:run",
    ]},
)
