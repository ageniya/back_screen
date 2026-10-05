"""ROS2/ament packaging entry for the unified robot back-screen."""

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
    packages=find_packages(exclude=["test"]),
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/robot_back_screen"]),
        (f"share/{PACKAGE_NAME}", ["package.xml", "requirements.txt"]),
        (f"share/{PACKAGE_NAME}/launch", ["launch/back_screen.launch.py"]),
    ] + web_data_files(),
    install_requires=["setuptools", "fastapi>=0.115,<1.0", "uvicorn[standard]>=0.30,<1.0", "websockets>=13,<16"],
    scripts=["deploy/start-pico-back-screen.sh"],
    zip_safe=False,
    maintainer="机器人软件组",
    maintainer_email="robot@example.invalid",
    description="机器人背屏 ROS2 数据服务与显示页面",
    license="Proprietary",
    entry_points={"console_scripts": ["robot-back-screen-api = robot_back_screen.main:run"]},
)
