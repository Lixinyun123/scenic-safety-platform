"""Supervise the two edge-to-cloud video forwarding processes on Windows.

The aircraft and Jetson stay on the isolated LQ-3 network. This process runs
on the dual-connected ground computer, pulls their RTSP streams and publishes
H.264 video to the public media server without re-encoding it.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import shutil
import signal
import socket
import subprocess
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parent
STOP = threading.Event()
STATUS_LOCK = threading.Lock()
STATUS: dict[str, object] = {"started_at": time.time(), "streams": {}}


def load_env(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def prevent_sleep() -> None:
    if os.name != "nt":
        return
    # ES_CONTINUOUS | ES_SYSTEM_REQUIRED. The display may turn off, but the
    # gateway process and network forwarding keep running.
    ctypes.windll.kernel32.SetThreadExecutionState(0x80000001)


def allow_sleep() -> None:
    if os.name == "nt":
        ctypes.windll.kernel32.SetThreadExecutionState(0x80000000)


def update_status(name: str, **values: object) -> None:
    with STATUS_LOCK:
        streams = STATUS.setdefault("streams", {})
        assert isinstance(streams, dict)
        stream = streams.setdefault(name, {})
        assert isinstance(stream, dict)
        stream.update(values, updated_at=time.time())
        temporary = ROOT / "gateway-status.json.tmp"
        destination = ROOT / "gateway-status.json"
        temporary.write_text(json.dumps(STATUS, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, destination)


def endpoint_reachable(value: str, timeout: float = 1.5) -> tuple[bool, str]:
    try:
        parsed = urlsplit(value)
        host = parsed.hostname
        port = parsed.port or (554 if parsed.scheme.startswith("rtsp") else 443)
        if not host:
            return False, "地址缺少主机名"
        with socket.create_connection((host, port), timeout=timeout):
            return True, f"{host}:{port} 可连接"
    except OSError as exc:
        return False, str(exc)


def ffmpeg_command(ffmpeg: str, source: str, destination: str) -> list[str]:
    return [
        ffmpeg,
        "-hide_banner",
        "-nostdin",
        "-loglevel",
        "warning",
        "-rtsp_transport",
        "tcp",
        "-rw_timeout",
        "12000000",
        "-i",
        source,
        "-map",
        "0:v:0",
        "-c:v",
        "copy",
        "-an",
        "-f",
        "flv",
        destination,
    ]


def supervise(name: str, source: str, destination: str, ffmpeg: str) -> None:
    delay = 2
    while not STOP.is_set():
        if not destination:
            update_status(name, state="waiting_for_server", detail="未配置云端推流地址")
            STOP.wait(5)
            continue
        reachable, detail = endpoint_reachable(source)
        if not reachable:
            update_status(name, state="source_offline", detail=detail)
            STOP.wait(min(delay, 15))
            delay = min(delay * 2, 15)
            continue
        update_status(name, state="starting", detail=detail)
        started = time.monotonic()
        process = subprocess.Popen(
            ffmpeg_command(ffmpeg, source, destination),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        update_status(name, state="publishing", pid=process.pid, detail="视频正在上传服务器")
        while process.poll() is None and not STOP.wait(1):
            pass
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
        runtime = time.monotonic() - started
        update_status(name, state="restarting", exit_code=process.returncode, detail="推流退出，准备重连")
        delay = 2 if runtime > 30 else min(delay * 2, 20)
        STOP.wait(delay)
    update_status(name, state="stopped", detail="网关已停止")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="LQ-3 Windows cloud video gateway")
    parser.add_argument("--env", type=Path, default=ROOT / "cloud-gateway.env")
    parser.add_argument("--check", action="store_true", help="only check configuration and local stream ports")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    load_env(args.env)
    ffmpeg_setting = os.environ.get("FFMPEG_PATH", "ffmpeg")
    ffmpeg = shutil.which(ffmpeg_setting) or (ffmpeg_setting if Path(ffmpeg_setting).is_file() else "")
    streams = {
        "station": (
            os.environ.get("STATION_SOURCE_URL", "rtsp://192.168.1.202:8554/station"),
            os.environ.get("CLOUD_STATION_PUBLISH_URL", ""),
        ),
        "drone": (
            os.environ.get("DRONE_SOURCE_URL", "rtsp://192.168.1.123:8554/rescue"),
            os.environ.get("CLOUD_DRONE_PUBLISH_URL", ""),
        ),
    }
    print(f"配置文件: {args.env}")
    print(f"FFmpeg: {ffmpeg or '未安装'}")
    for name, (source, destination) in streams.items():
        reachable, detail = endpoint_reachable(source)
        print(f"{name}: 本地源{'正常' if reachable else '不可达'} ({detail}); 云端{'已配置' if destination else '未配置'}")
    if args.check:
        return 0 if ffmpeg and all(endpoint_reachable(source)[0] for source, _ in streams.values()) else 2
    if not ffmpeg:
        raise SystemExit("未找到 FFmpeg。安装后在 cloud-gateway.env 中设置 FFMPEG_PATH。")

    signal.signal(signal.SIGINT, lambda *_: STOP.set())
    signal.signal(signal.SIGTERM, lambda *_: STOP.set())
    prevent_sleep()
    threads = [
        threading.Thread(target=supervise, args=(name, source, destination, ffmpeg), daemon=True)
        for name, (source, destination) in streams.items()
    ]
    try:
        for thread in threads:
            thread.start()
        while any(thread.is_alive() for thread in threads):
            for thread in threads:
                thread.join(timeout=1)
    finally:
        STOP.set()
        allow_sleep()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
