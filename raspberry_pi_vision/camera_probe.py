"""检查 SJ4000 是否被树莓派识别成 USB 摄像头，并拍一张测试图。"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

import cv2


def run_command(command: list[str]) -> None:
    try:
        result = subprocess.run(command, check=False, text=True, capture_output=True)
    except FileNotFoundError:
        print(f"[SKIP] 未安装 {command[0]}")
        return
    output = (result.stdout or result.stderr).strip()
    if output:
        print(f"$ {' '.join(command)}\n{output}\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="SJ4000 USB 摄像头检查")
    parser.add_argument("--index", type=int, default=0, help="摄像头序号，默认 0")
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    parser.add_argument("--output", default="output/camera_test.jpg")
    args = parser.parse_args()

    run_command(["lsusb"])
    run_command(["v4l2-ctl", "--list-devices"])
    run_command(
        ["v4l2-ctl", f"--device=/dev/video{args.index}", "--list-formats-ext"]
    )

    cap = cv2.VideoCapture(args.index, cv2.CAP_V4L2)
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, args.width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, args.height)
    cap.set(cv2.CAP_PROP_FPS, 30)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

    if not cap.isOpened():
        print(
            f"[FAIL] 打不开 /dev/video{args.index}。\n"
            "1. SJ4000 开机后选 WEB CAM/PC Camera；\n"
            "2. 换一条能传数据的 USB 线；\n"
            "3. 执行 v4l2-ctl --list-devices 确认序号。"
        )
        return 2

    frame = None
    # 丢弃刚开启时的旧帧，等待自动曝光稳定。
    for _ in range(30):
        ok, candidate = cap.read()
        if ok:
            frame = candidate
    cap.release()

    if frame is None:
        print("[FAIL] 摄像头已打开，但没有读到画面。")
        return 3

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(output), frame):
        print(f"[FAIL] 无法保存 {output}")
        return 4


    height, width = frame.shape[:2]
    print(f"[OK] 已读到 {width}x{height} 画面，测试图：{output.resolve()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
