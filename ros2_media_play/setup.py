from setuptools import setup

package_name = "zj_media_play"

setup(
    name=package_name,
    version="0.1.0",
    packages=[package_name],
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/zj_media_play"]),
        (f"share/{package_name}", ["package.xml"]),
        (f"share/{package_name}/launch", ["launch/media_play.launch.py"]),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="Robot Team",
    maintainer_email="robot@example.invalid",
    description="ROS2 on-demand face video player for the Pico rear display.",
    license="MIT",
    entry_points={
        "console_scripts": [
            "media_play_node = zj_media_play.media_play_node:main",
        ],
    },
)
