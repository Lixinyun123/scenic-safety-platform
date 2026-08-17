"""Raspberry Pi 5 + SJCAM SJ4000 实时疑似人员检测。"""

from __future__ import annotations

import argparse
import base64
import hmac
import json
import os
import signal
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import cv2

from detection_logic import PersonConfirmer
from ncnn_person_detector import NCNNPersonDetector, draw_detections


WEB_DIR = Path(__file__).with_name("web")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="使用 SJ4000 USB 视频检测 person，连续多帧确认后保存证据。"
    )
    parser.add_argument(
        "--camera",
        default="/dev/v4l/by-id/usb-SJCAM_4000-video-index0",
        help="摄像头编号或稳定设备路径",
    )
    parser.add_argument(
        "--model",
        default="yolo26n_640x384_ncnn_model",
        help="NCNN 模型目录",
    )
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    parser.add_argument("--img-width", type=int, default=640, help="NCNN 输入宽度")
    parser.add_argument("--img-height", type=int, default=384, help="NCNN 输入高度")
    parser.add_argument("--threads", type=int, default=4, help="NCNN CPU 推理线程数")
    parser.add_argument("--iou", type=float, default=0.45, help="人员框 NMS 阈值")
    parser.add_argument(
        "--inference-fps",
        type=float,
        default=10.0,
        help="Maximum AI inference rate; the RTSP reader still drains newer frames",
    )
    parser.add_argument("--confidence", type=float, default=0.45)
    parser.add_argument("--confirm-frames", type=int, default=5)
    parser.add_argument("--cooldown", type=float, default=30.0, help="截图最小间隔（秒）")
    parser.add_argument("--output", default="output")
    parser.add_argument("--no-display", action="store_true", help="SSH/无显示器模式")
    parser.add_argument("--max-frames", type=int, default=0, help="处理指定帧数后退出，0 表示持续运行")
    parser.add_argument("--status-interval", type=float, default=5.0, help="终端状态输出间隔（秒）")
    parser.add_argument("--web", action="store_true", help="开启浏览器实时识别画面")
    parser.add_argument("--web-host", default="0.0.0.0", help="网页监听地址")
    parser.add_argument("--web-port", type=int, default=8080, help="网页端口")
    parser.add_argument("--web-width", type=int, default=1280, help="网页画面最大宽度")
    parser.add_argument("--web-quality", type=int, default=90, help="网页 JPEG 质量")
    parser.add_argument(
        "--public-fps",
        type=float,
        default=6.0,
        help="Tailscale Funnel public preview FPS; does not affect detection FPS",
    )
    return parser.parse_args()


class FrameStream:
    """在线程之间传递最新的一帧 JPEG，慢客户端不会拖慢识别。"""

    def __init__(self, width: int, quality: int) -> None:
        self.condition = threading.Condition()
        self.jpeg: bytes | None = None
        self.sequence = 0
        self.clients = 0
        self.width = width
        self.quality = quality
        self.pending_frame = None
        threading.Thread(target=self._encode_loop, daemon=True, name="web-jpeg-encoder").start()

    def add_client(self, amount: int) -> None:
        with self.condition:
            self.clients = max(0, self.clients + amount)

    def update(self, frame) -> None:
        with self.condition:
            if self.clients == 0:
                return
            # 只保留最新帧；网页编码再慢也不会阻塞识别主循环或积压旧画面。
            self.pending_frame = frame.copy()
            self.condition.notify_all()

    def _encode_loop(self) -> None:
        while True:
            with self.condition:
                self.condition.wait_for(lambda: self.pending_frame is not None)
                frame = self.pending_frame
                self.pending_frame = None
            if frame.shape[1] > self.width:
                scale = self.width / frame.shape[1]
                frame = cv2.resize(frame, (self.width, int(frame.shape[0] * scale)))
            ok, encoded = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, self.quality])
            if not ok:
                continue
            with self.condition:
                self.jpeg = encoded.tobytes()
                self.sequence += 1
                self.condition.notify_all()

    def wait_for_next(self, sequence: int) -> tuple[int, bytes | None]:
        with self.condition:
            self.condition.wait_for(lambda: self.sequence != sequence, timeout=2.0)
            return self.sequence, self.jpeg


class DetectionState:
    """Thread-safe lightweight metadata for the browser overlay."""

    def __init__(self, path: Path | None = None) -> None:
        self.lock = threading.Lock()
        self.path = path
        self.last_write = 0.0
        self.value = {
            "connected": False,
            "width": 1280,
            "height": 720,
            "fps": 0.0,
            "people": 0,
            "confirmed": False,
            "boxes": [],
            "updated": 0.0,
        }
        self._write_file(force=True)

    def _write_file(self, force: bool = False) -> None:
        if self.path is None:
            return
        now = time.monotonic()
        if not force and now - self.last_write < 0.2:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(json.dumps(self.value, ensure_ascii=False), encoding="utf-8")
        os.replace(temporary, self.path)
        self.last_write = now

    def update(self, frame, detections, fps: float, confirmed: bool) -> None:
        height, width = frame.shape[:2]
        value = {
            "connected": True,
            "width": width,
            "height": height,
            "fps": round(fps, 1),
            "people": len(detections),
            "confirmed": confirmed,
            "boxes": [
                {
                    "x1": detection.box[0],
                    "y1": detection.box[1],
                    "x2": detection.box[2],
                    "y2": detection.box[3],
                    "confidence": round(detection.confidence, 3),
                }
                for detection in detections
            ],
            "updated": time.time(),
        }
        with self.lock:
            self.value = value
            self._write_file()

    def mark_offline(self, reason: str) -> None:
        with self.lock:
            self.value.update(
                connected=False,
                fps=0.0,
                people=0,
                confirmed=False,
                boxes=[],
                offline_reason=reason,
                updated=time.time(),
            )
            self._write_file(force=True)

    def snapshot(self) -> bytes:
        with self.lock:
            value = dict(self.value)
            value["boxes"] = list(self.value["boxes"])
        return json.dumps(value, ensure_ascii=False).encode("utf-8")


class FlightTelemetryFile:
    """Read the latest MAVLink snapshot produced by the future flight bridge."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.empty = {
            "connected": False,
            "latitude": None,
            "longitude": None,
            "relative_altitude": None,
            "height_agl": None,
            "height_source": None,
            "range_updated": 0.0,
            "optical_flow_quality": None,
            "ground_speed": None,
            "heading": None,
            "battery_percent": None,
            "battery_voltage": None,
            "satellites": None,
            "gps_fix": None,
            "flight_mode": None,
            "armed": None,
            "ekf_flags": 0,
            "flight_message": None,
            "command_result": None,
            "updated": 0.0,
        }

    def snapshot(self) -> bytes:
        value = dict(self.empty)
        try:
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                value.update({key: loaded.get(key) for key in value})
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            pass
        return json.dumps(value, ensure_ascii=False).encode("utf-8")


WEBRTC_PAGE = """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>树莓派落水人员识别</title>
<style>
*{box-sizing:border-box}body{margin:0;background:#101216;color:#eef;font-family:system-ui;text-align:center}
main{max-width:1320px;margin:auto;padding:12px}h1{font-size:21px;margin:4px 0 10px}
.stage{position:relative;width:100%;aspect-ratio:16/9;background:#050607;border-radius:10px;overflow:hidden}
iframe,img,canvas{position:absolute;inset:0;width:100%;height:100%;border:0}img{object-fit:contain}
canvas{pointer-events:none}.bar{display:flex;justify-content:center;gap:22px;margin:9px;color:#bbc}
.live{color:#59dc78}.alert{color:#ff5757;font-weight:700}.hint{font-size:13px;color:#89919f}
</style></head><body><main><h1>树莓派实时人员识别</h1>
<div class="stage"><iframe id="rtc" allow="autoplay; fullscreen"></iframe>
<img id="fallback" alt="实时识别画面" hidden><canvas id="overlay"></canvas></div>
<div class="bar"><span id="mode" class="live">● 正在连接</span><span id="fps">识别 FPS --</span><span id="people">人员 0</span></div>
<div class="hint">绿色框为实时识别结果；视频与识别数据分开传输，避免旧画面排队。</div>
</main><script>
const rtc=document.getElementById('rtc'), fallback=document.getElementById('fallback');
const canvas=document.getElementById('overlay'), ctx=canvas.getContext('2d');
const funnel=location.hostname.endsWith('.ts.net');
if(funnel){rtc.src=`https://${location.hostname}:8443/rescue?controls=false&muted=true&autoplay=true&playsInline=true`;document.getElementById('mode').textContent='● H.264 公网低延迟模式'}
else{rtc.src=`http://${location.hostname}:8889/rescue?controls=false&muted=true&autoplay=true&playsInline=true`;document.getElementById('mode').textContent='● H.264 WebRTC 低延迟模式'}
function resize(){const r=canvas.getBoundingClientRect();canvas.width=Math.round(r.width*devicePixelRatio);canvas.height=Math.round(r.height*devicePixelRatio)}
addEventListener('resize',resize);resize();
async function update(){try{const statusUrl=`${location.protocol}//${location.hostname}:${location.port}/status.json`;const s=await fetch(statusUrl,{cache:'no-store'}).then(r=>r.json());
ctx.clearRect(0,0,canvas.width,canvas.height);const sx=canvas.width/s.width,sy=canvas.height/s.height;
ctx.lineWidth=3*devicePixelRatio;ctx.font=`${18*devicePixelRatio}px system-ui`;
for(const b of s.boxes){const x=b.x1*sx,y=b.y1*sy,w=(b.x2-b.x1)*sx,h=(b.y2-b.y1)*sy;ctx.strokeStyle='#20ff65';ctx.fillStyle='#20ff65';ctx.strokeRect(x,y,w,h);ctx.fillText(`person ${b.confidence.toFixed(2)}`,x,Math.max(20*devicePixelRatio,y-6*devicePixelRatio))}
document.getElementById('fps').textContent=`识别 FPS ${s.fps.toFixed(1)}`;document.getElementById('people').textContent=`人员 ${s.people}`;
document.getElementById('people').className=s.confirmed?'alert':'';}catch(e){document.getElementById('fps').textContent=`识别数据错误: ${e.message}`;console.error(e)}setTimeout(update,100)}update();
</script></body></html>"""


def start_web_server(
    stream: FrameStream,
    detection_state: DetectionState,
    flight_telemetry: FlightTelemetryFile,
    host: str,
    port: int,
    public_fps: float,
) -> ThreadingHTTPServer:
    username = os.environ.get("WEB_USERNAME", "")
    password = os.environ.get("WEB_PASSWORD", "")
    public_access = os.environ.get("WEB_PUBLIC", "").lower() in ("1", "true", "yes")
    expected_authorization = "Basic " + base64.b64encode(
        f"{username}:{password}".encode("utf-8")
    ).decode("ascii")
    session_token = base64.urlsafe_b64encode(os.urandom(24)).decode("ascii")

    class StreamHandler(BaseHTTPRequestHandler):
        def send_json_response(self, status: int, body: bytes, refresh_session: bool = False) -> None:
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            if refresh_session:
                self.send_header(
                    "Set-Cookie",
                    f"rescue_session={session_token}; Path=/; HttpOnly; SameSite=Strict",
                )
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def has_session(self) -> bool:
            for item in self.headers.get("Cookie", "").split(";"):
                key, separator, value = item.strip().partition("=")
                if separator and key == "rescue_session":
                    return hmac.compare_digest(value, session_token)
            return False

        def do_POST(self) -> None:
            if self.path != "/api/flight-command":
                self.send_error(404)
                return
            if not self.has_session():
                self.send_json_response(403, json.dumps({"ok": False, "error": "网页控制会话无效"}, ensure_ascii=False).encode("utf-8"))
                return
            try:
                length = min(int(self.headers.get("Content-Length", "0")), 1024)
                value = json.loads(self.rfile.read(length) or b"{}")
                pin = str(value.pop("pin", ""))
                request = urllib.request.Request(
                    "http://127.0.0.1:8091/command",
                    data=json.dumps(value).encode("utf-8"),
                    headers={"Content-Type": "application/json", "X-Control-Pin": pin},
                    method="POST",
                )
                try:
                    with urllib.request.urlopen(request, timeout=6) as response:
                        status, body = response.status, response.read()
                except urllib.error.HTTPError as error:
                    status, body = error.code, error.read()
            except (ValueError, json.JSONDecodeError, OSError, urllib.error.URLError) as error:
                status = 502
                body = json.dumps({"ok": False, "error": f"控制服务不可用: {error}"}, ensure_ascii=False).encode("utf-8")
            self.send_json_response(status, body)

        def do_GET(self) -> None:
            # This endpoint contains only transient box coordinates and FPS.
            # Keeping it credential-free lets authenticated pages poll it
            # without embedding the camera password in JavaScript.
            if self.path == "/status.json":
                body = detection_state.snapshot()
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return

            if self.path == "/telemetry.json":
                body = flight_telemetry.snapshot()
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return

            if self.path == "/api/control/status":
                try:
                    with urllib.request.urlopen("http://127.0.0.1:8091/status", timeout=2) as response:
                        body = response.read()
                    self.send_json_response(200, body, refresh_session=True)
                except (OSError, urllib.error.URLError):
                    self.send_json_response(503, b'{"enabled":false,"takeoff_enabled":false}', refresh_session=True)
                return

            authorization = self.headers.get("Authorization", "")
            cookie = self.headers.get("Cookie", "")
            cookie_token = ""
            for item in cookie.split(";"):
                key, separator, value = item.strip().partition("=")
                if separator and key == "rescue_session":
                    cookie_token = value
                    break
            basic_ok = hmac.compare_digest(authorization, expected_authorization)
            session_ok = hmac.compare_digest(cookie_token, session_token)
            if not public_access and (
                not username or not password or not (basic_ok or session_ok)
            ):
                self.send_response(401)
                self.send_header("WWW-Authenticate", 'Basic realm="Water Rescue Camera"')
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                return

            if self.path == "/status.json":
                body = detection_state.snapshot()
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return

            static_files = {
                "/": (WEB_DIR / "index.html", "text/html; charset=utf-8"),
                "/index.html": (WEB_DIR / "index.html", "text/html; charset=utf-8"),
                "/assets/dashboard.css": (WEB_DIR / "dashboard.css", "text/css; charset=utf-8"),
                "/assets/dashboard.js": (
                    WEB_DIR / "dashboard.js",
                    "application/javascript; charset=utf-8",
                ),
            }
            if self.path in static_files:
                file_path, content_type = static_files[self.path]
                body = (
                    file_path.read_bytes()
                    if file_path.exists()
                    else WEBRTC_PAGE.encode("utf-8")
                )
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Cache-Control", "no-store")
                if self.path in ("/", "/index.html"):
                    self.send_header(
                        "Set-Cookie",
                        f"rescue_session={session_token}; Path=/; HttpOnly; SameSite=Strict",
                    )
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return

            if self.path == "/legacy.html":
                page = """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>树莓派落水人员识别</title>
<style>
body{margin:0;background:#111;color:#eee;font-family:system-ui;text-align:center}
main{max-width:1280px;margin:auto;padding:16px}h1{font-size:22px;margin:4px 0 12px}
img{display:block;width:100%;height:auto;background:#222;border-radius:10px}
p{color:#aaa;margin:10px}.ok{color:#53d769}
</style></head><body><main><h1>树莓派实时人员识别</h1>
<img src="/stream.mjpg" alt="实时识别画面">
<p><span class="ok">● 正在运行</span>　画面中的框、FPS 和确认状态由树莓派实时生成</p>
</main></body></html>"""
                body = page.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return

            if self.path != "/stream.mjpg":
                self.send_error(404)
                return

            # Funnel proxies public requests through a local loopback connection.
            # Bound the queue and rate so stale JPEG frames cannot accumulate.
            is_funnel = self.client_address[0] in ("127.0.0.1", "::1")
            if is_funnel:
                self.connection.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 64 * 1024)
                self.connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

            self.send_response(200)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Pragma", "no-cache")
            self.send_header("X-Accel-Buffering", "no")
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
            self.end_headers()
            sequence = -1
            send_interval = 1.0 / max(public_fps, 1.0) if is_funnel else 0.0
            next_send = time.monotonic()
            stream.add_client(1)
            try:
                while True:
                    if send_interval:
                        delay = next_send - time.monotonic()
                        if delay > 0:
                            time.sleep(delay)
                    sequence, jpeg = stream.wait_for_next(sequence)
                    if jpeg is None:
                        continue
                    self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\n")
                    self.wfile.write(f"Content-Length: {len(jpeg)}\r\n\r\n".encode())
                    self.wfile.write(jpeg)
                    self.wfile.write(b"\r\n")
                    self.wfile.flush()
                    if send_interval:
                        # Never catch up after a slow send: fetch only the newest frame.
                        next_send = time.monotonic() + send_interval
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass
            finally:
                stream.add_client(-1)

        def log_message(self, _format: str, *_args) -> None:
            return

    server = ThreadingHTTPServer((host, port), StreamHandler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


class LatestFrameCapture:
    """Continuously drain a network stream and expose only its newest frame."""

    def __init__(self, capture) -> None:
        self.capture = capture
        self.condition = threading.Condition()
        self.frame = None
        self.sequence = 0
        self.consumed_sequence = -1
        self.stopped = False
        self.opened = capture.isOpened()
        if self.opened:
            self.thread = threading.Thread(
                target=self._reader, daemon=True, name="latest-rtsp-frame"
            )
            self.thread.start()
        else:
            self.thread = None

    def _reader(self) -> None:
        while not self.stopped:
            ok, frame = self.capture.read()
            if not ok:
                with self.condition:
                    self.opened = False
                    self.condition.notify_all()
                return
            with self.condition:
                self.frame = frame
                self.sequence += 1
                self.condition.notify_all()

    def isOpened(self) -> bool:
        return self.opened

    def read(self):
        with self.condition:
            self.condition.wait_for(
                lambda: self.sequence != self.consumed_sequence or not self.opened,
                timeout=2.0,
            )
            if self.frame is None or not self.opened:
                return False, None
            self.consumed_sequence = self.sequence
            return True, self.frame.copy()

    def release(self) -> None:
        self.stopped = True
        self.capture.release()
        if self.thread:
            self.thread.join(timeout=1.0)


def open_camera(source: str, width: int, height: int):
    if source.startswith(("rtsp://", "rtsps://")):
        os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = (
            "rtsp_transport;tcp|fflags;nobuffer|flags;low_delay|max_delay;0"
        )
        capture = cv2.VideoCapture(source, cv2.CAP_FFMPEG)
        capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        return LatestFrameCapture(capture)

    camera_source: int | str = int(source) if source.isdigit() else source
    cap = cv2.VideoCapture(camera_source, cv2.CAP_V4L2)
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
    cap.set(cv2.CAP_PROP_FPS, 30)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    return cap


def draw_status(frame, fps: float, count: int, confirmed: bool) -> None:
    color = (0, 0, 255) if confirmed else (0, 200, 255)
    status = "PERSON CONFIRMED" if confirmed else f"checking {count}"
    cv2.rectangle(frame, (0, 0), (frame.shape[1], 38), (20, 20, 20), -1)
    cv2.putText(
        frame,
        f"{status} | FPS {fps:.1f}",
        (10, 27),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.7,
        color,
        2,
        cv2.LINE_AA,
    )


def save_evidence(image_path: Path, frame, event: dict, log_path: Path) -> None:
    cv2.imwrite(str(image_path), frame, [cv2.IMWRITE_JPEG_QUALITY, 95])
    with log_path.open("a", encoding="utf-8") as log_file:
        log_file.write(json.dumps(event, ensure_ascii=False) + "\n")
    print(f"[ALERT] 连续多帧发现疑似人员，已保存 {image_path}")


def main() -> int:
    args = parse_args()
    if not 0.0 < args.confidence <= 1.0:
        raise ValueError("--confidence must be in (0, 1]")
    if args.inference_fps <= 0:
        raise ValueError("--inference-fps must be greater than 0")

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)
    log_path = output_dir / "detections.jsonl"

    print(f"[INFO] 加载模型：{args.model}")
    model = NCNNPersonDetector(args.model, args.img_width, args.img_height, args.threads)
    stream = FrameStream(args.web_width, args.web_quality) if args.web else None
    detection_state = DetectionState(output_dir / "detection_status.json")
    flight_telemetry = FlightTelemetryFile(output_dir / "flight_telemetry.json")
    web_server = (
        start_web_server(
            stream,
            detection_state,
            flight_telemetry,
            args.web_host,
            args.web_port,
            args.public_fps,
        )
        if stream
        else None
    )
    if web_server:
        print(f"[INFO] 实时画面：http://<树莓派IP>:{args.web_port}")
    cap = open_camera(args.camera, args.width, args.height)

    if not cap.isOpened():
        detection_state.mark_offline("camera_unavailable")
        print(f"[FAIL] 打不开摄像头 {args.camera}，请先运行 camera_probe.py。")
        return 2

    confirmer = PersonConfirmer(args.confirm_frames)
    evidence_writer = ThreadPoolExecutor(max_workers=1, thread_name_prefix="evidence-writer")
    stop = False

    def request_stop(_signum, _frame) -> None:
        nonlocal stop
        stop = True

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)

    last_capture_time = -args.cooldown
    previous_time = time.monotonic()
    started_at = previous_time
    last_status_time = previous_time
    smoothed_fps = 0.0
    processed_frames = 0
    read_failures = 0
    inference_interval = 1.0 / args.inference_fps
    next_inference_time = time.monotonic()
    print("[INFO] 开始检测。按 q 或 Ctrl+C 退出。")

    try:
        while not stop:
            delay = next_inference_time - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            ok, frame = cap.read()
            if not ok:
                read_failures += 1
                if read_failures == 1:
                    print("[WARN] 摄像头断流，正在自动重连……")
                if read_failures >= 10:
                    cap.release()
                    time.sleep(0.5)
                    cap = open_camera(args.camera, args.width, args.height)
                    read_failures = 0
                time.sleep(0.05)
                continue
            read_failures = 0
            next_inference_time = time.monotonic() + inference_interval

            detections = model.detect(frame, args.confidence, args.iou)
            person_count = len(detections)
            state = confirmer.update(person_count > 0)
            annotated = draw_detections(frame, detections)
            processed_frames += 1

            now = time.monotonic()
            instantaneous_fps = 1.0 / max(now - previous_time, 1e-6)
            previous_time = now
            smoothed_fps = instantaneous_fps if smoothed_fps == 0 else 0.9 * smoothed_fps + 0.1 * instantaneous_fps
            draw_status(annotated, smoothed_fps, state.consecutive_frames, state.confirmed)
            detection_state.update(frame, detections, smoothed_fps, state.confirmed)
            if stream:
                stream.update(annotated)

            if now - last_status_time >= args.status_interval:
                print(
                    f"[STATUS] frames={processed_frames} "
                    f"fps={smoothed_fps:.1f} people={person_count} "
                    f"confirmed={state.confirmed}"
                )
                last_status_time = now

            if state.just_confirmed and now - last_capture_time >= args.cooldown:
                stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
                image_path = output_dir / f"person_{stamp}.jpg"
                event = {
                    "time": datetime.now().astimezone().isoformat(),
                    "event": "suspected_person_confirmed",
                    "person_count": person_count,
                    "confidence_threshold": args.confidence,
                    "image": str(image_path),
                }
                evidence_writer.submit(save_evidence, image_path, annotated.copy(), event, log_path)
                last_capture_time = now

            if not args.no_display:
                cv2.imshow("Raspberry Pi Water Person Detector", annotated)
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    break

            if args.max_frames > 0 and processed_frames >= args.max_frames:
                break
    finally:
        detection_state.mark_offline("detector_stopped")
        cap.release()
        cv2.destroyAllWindows()
        if web_server:
            web_server.shutdown()
            web_server.server_close()
        evidence_writer.shutdown(wait=True)

    elapsed = max(time.monotonic() - started_at, 1e-6)
    print(
        f"[INFO] 检测已停止。frames={processed_frames} "
        f"elapsed={elapsed:.1f}s average_fps={processed_frames / elapsed:.1f}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
