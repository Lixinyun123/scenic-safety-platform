"""Extract non-blurry training frames from train/val video folders."""

from __future__ import annotations

import argparse
from pathlib import Path

import cv2


VIDEO_SUFFIXES = {".mp4", ".mov", ".avi", ".mkv", ".m4v"}


def extract_video(video: Path, output: Path, seconds: float, blur_threshold: float) -> tuple[int, int]:
    capture = cv2.VideoCapture(str(video))
    if not capture.isOpened():
        print(f"[跳过] 无法打开：{video}")
        return 0, 0
    fps = capture.get(cv2.CAP_PROP_FPS) or 30.0
    stride = max(1, round(fps * seconds))
    frame_index = 0
    saved = 0
    blurry = 0
    while True:
        ok, frame = capture.read()
        if not ok:
            break
        if frame_index % stride == 0:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            sharpness = cv2.Laplacian(gray, cv2.CV_64F).var()
            if sharpness >= blur_threshold:
                image_path = output / f"{video.stem}_f{frame_index:08d}.jpg"
                cv2.imwrite(str(image_path), frame, [cv2.IMWRITE_JPEG_QUALITY, 95])
                saved += 1
            else:
                blurry += 1
        frame_index += 1
    capture.release()
    return saved, blurry


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--seconds", type=float, default=1.0, help="每隔多少秒抽一帧")
    parser.add_argument("--blur-threshold", type=float, default=45.0)
    args = parser.parse_args()
    if args.seconds <= 0:
        raise ValueError("--seconds 必须大于0")

    total = 0
    for split in ("train", "val"):
        source = args.root / "raw_videos" / split
        output = args.root / "dataset" / "images" / split
        output.mkdir(parents=True, exist_ok=True)
        videos = sorted(path for path in source.iterdir() if path.suffix.lower() in VIDEO_SUFFIXES)
        print(f"[{split}] 找到 {len(videos)} 个视频")
        for video in videos:
            saved, blurry = extract_video(video, output, args.seconds, args.blur_threshold)
            total += saved
            print(f"  {video.name}: 保存 {saved} 帧，过滤模糊帧 {blurry} 张")
    print(f"完成，共保存 {total} 张图片。下一步需要人工标注。")


if __name__ == "__main__":
    main()
