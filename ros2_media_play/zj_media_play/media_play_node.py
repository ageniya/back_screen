"""Play face media on demand without taking over the rear display at boot."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import threading
from typing import Optional
import json
import socket

import rclpy
from rclpy.node import Node
from navi_robot_msgs.srv import FaceShow
from std_msgs.msg import String
from std_srvs.srv import Trigger


class MediaPlayNode(Node):
    """Compatibility service for the old face-show media API."""

    def __init__(self) -> None:
        super().__init__("media_play")
        self.declare_parameter("media_dir", "/opt/zj_humanoid/media_play")
        self.declare_parameter("display", ":1")
        self.declare_parameter("xauthority", "/run/user/1000/gdm/Xauthority")
        self.declare_parameter("mpv_binary", "mpv")
        self.declare_parameter("subtitle_duration_ms", 5000)
        self.declare_parameter("mpv_ipc_socket", "/tmp/zj_media_play_mpv_1000.sock")
        self._process: Optional[subprocess.Popen] = None
        self._timer: Optional[threading.Timer] = None
        self._lock = threading.Lock()
        self._status = self.create_publisher(String, "status", 10)
        self._service = self.create_service(FaceShow, "media_play", self._handle_play)
        self._stop_service = self.create_service(Trigger, "media_stop", self._handle_stop)
        self._customer_sub = self.create_subscription(
            String, "/zj_humanoid/subtitle/customer", self._on_customer_subtitle, 10
        )
        self._robot_sub = self.create_subscription(
            String, "/zj_humanoid/subtitle/robot", self._on_robot_subtitle, 10
        )
        self.get_logger().info(
            "媒体播放器已待命：收到服务调用才播放；已订阅客户和机器人字幕话题。"
        )

    def _publish_status(self, text: str) -> None:
        self._status.publish(String(data=text))

    def _media_path(self, requested: str) -> Path:
        media_dir = Path(self.get_parameter("media_dir").value).resolve()
        candidate = Path(requested)
        resolved = candidate.resolve() if candidate.is_absolute() else (media_dir / candidate).resolve()
        if resolved != media_dir and media_dir not in resolved.parents:
            raise ValueError("媒体路径必须位于允许的视频目录中")
        if not resolved.is_file():
            raise FileNotFoundError(f"未找到媒体文件：{resolved}")
        return resolved

    def _stop_locked(self) -> None:
        if self._timer:
            self._timer.cancel()
            self._timer = None
        if self._process and self._process.poll() is None:
            self._process.terminate()
        self._process = None
        try:
            Path(str(self.get_parameter("mpv_ipc_socket").value)).unlink(missing_ok=True)
        except OSError as exc:
            self.get_logger().warning(f"清理播放器 IPC 文件失败：{exc}")

    def _show_subtitle(self, prefix: str, text: str) -> None:
        """Use mpv's IPC OSD, matching the behaviour of the ROS1 package."""
        text = text.strip()
        if not text:
            return
        ipc_path = str(self.get_parameter("mpv_ipc_socket").value)
        if not Path(ipc_path).exists():
            self.get_logger().info(f"当前没有正在播放的面部视频，字幕不显示：{text}")
            self._publish_status("subtitle_ignored:no_active_video")
            return
        duration = max(100, int(self.get_parameter("subtitle_duration_ms").value))
        command = {"command": ["show-text", f"{prefix} {text}", duration, 1]}
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                client.settimeout(1.0)
                client.connect(ipc_path)
                client.sendall((json.dumps(command, ensure_ascii=False) + "\n").encode())
                reply = client.recv(4096).decode(errors="replace")
                if '"error":"success"' not in reply:
                    raise OSError(f"mpv 拒绝字幕命令：{reply.strip()}")
            self._publish_status(f"subtitle:{text}")
        except OSError as exc:
            self.get_logger().warning(f"字幕发送给播放器失败：{exc}")

    def _on_customer_subtitle(self, message: String) -> None:
        self._show_subtitle("用户：", message.data)

    def _on_robot_subtitle(self, message: String) -> None:
        self._show_subtitle("机器人：", message.data)

    def _stop_after_duration(self) -> None:
        with self._lock:
            self._stop_locked()
        self._publish_status("stopped")

    def _handle_stop(self, _request: Trigger.Request, response: Trigger.Response) -> Trigger.Response:
        """Allow a caller to close the face video immediately."""
        with self._lock:
            playing = self._process is not None and self._process.poll() is None
            self._stop_locked()
        response.success = True
        response.message = "已停止面部视频" if playing else "当前没有正在播放的视频"
        self._publish_status("stopped")
        return response

    def _handle_play(self, request: FaceShow.Request, response: FaceShow.Response) -> FaceShow.Response:
        try:
            media_path = self._media_path(request.media_path)
            with self._lock:
                self._stop_locked()
                env = os.environ.copy()
                env["DISPLAY"] = str(self.get_parameter("display").value)
                env["XAUTHORITY"] = str(self.get_parameter("xauthority").value)
                command = [
                    str(self.get_parameter("mpv_binary").value),
                    "--force-window=yes",
                    "--fullscreen=yes",
                    "--ontop=yes",
                    "--no-terminal",
                    "--keep-open=no",
                    "--really-quiet",
                    "--no-audio",
                    # 保留 show-text 的 1 级字幕 OSD，不显示 mpv 的播放进度等调试信息。
                    "--osd-level=1",
                    "--osd-font-size=42",
                    "--osd-align-x=center",
                    # Pico 的软键盘会覆盖画面底部；字幕放到顶部始终可见。
                    "--osd-align-y=top",
                    "--osd-margin-y=40",
                    "--osd-color=#FFFFFFFF",
                    "--osd-border-color=#000000FF",
                    "--osd-border-size=3",
                    f"--input-ipc-server={self.get_parameter('mpv_ipc_socket').value}",
                ]
                if request.loop:
                    command.append("--loop-file=inf")
                command.append(str(media_path))
                self._process = subprocess.Popen(command, env=env)
                if request.duration > 0:
                    self._timer = threading.Timer(request.duration, self._stop_after_duration)
                    self._timer.daemon = True
                    self._timer.start()
            response.success = True
            response.status_code = 0
            response.message = f"正在播放：{media_path.name}"
            self._publish_status(f"playing:{media_path.name}")
        except (OSError, ValueError) as exc:
            response.success = False
            response.status_code = 1
            response.message = str(exc)
            self.get_logger().warning(response.message)
        return response

    def destroy_node(self) -> bool:
        with self._lock:
            self._stop_locked()
        return super().destroy_node()


def main() -> None:
    rclpy.init()
    node = MediaPlayNode()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
