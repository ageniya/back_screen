# Pico 按需面部视频（ROS2）

该包供 Pico 屏幕播放面部视频。节点启动后只待命，**不会自动播放**；调用播放服务时才会全屏置顶启动 `mpv`。视频结束、到达定时长度、调用停止服务或播放另一段视频后，Firefox 背屏会重新可见。

## ROS2 接口

| 接口 | 类型 | 用途 |
| --- | --- | --- |
| `/zj_humanoid/robot/face_show/media_play` | `navi_robot_msgs/srv/FaceShow` | 播放指定视频 |
| `/zj_humanoid/robot/face_show/media_stop` | `std_srvs/srv/Trigger` | 立即停止视频 |
| `/zj_humanoid/robot/face_show/status` | `std_msgs/msg/String` | 播放、停止、字幕状态 |
| `/zj_humanoid/subtitle/customer` | `std_msgs/msg/String` | 显示客户字幕 |
| `/zj_humanoid/subtitle/robot` | `std_msgs/msg/String` | 显示机器人字幕 |

`FaceShow` 字段：`media_path` 为视频相对文件名，`loop` 为是否循环，`duration` 为秒数；`duration: 0.0` 表示不定时，由视频自然结束或停止服务结束。

`media_path` 只能引用 `media_dir` 内的文件，默认目录为 `/opt/zj_humanoid/media_play`，不能访问任意本机路径。

完整部署、调用和验收方法见 [视频包交付测试.md](../docs/视频包交付测试.md)。
