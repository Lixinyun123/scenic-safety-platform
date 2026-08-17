"""Camera-independent web dashboard and data-source gateway.

The server deliberately depends only on Python's standard library.  It stays
available when vision, MediaMTX, the flight controller, or a future 4G ground
terminal is offline.
"""

from __future__ import annotations

import argparse
import base64
import hmac
import json
import mimetypes
import os
import secrets
import time
import urllib.error
import urllib.request
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


ROOT = Path(__file__).resolve().parent
WEB_DIR = ROOT / "web"

VISION_EMPTY = {
    "source": "vision",
    "connected": False,
    "width": 1280,
    "height": 720,
    "fps": 0.0,
    "people": 0,
    "confirmed": False,
    "boxes": [],
    "updated": 0.0,
}

FLIGHT_EMPTY = {
    "source": "flight_controller",
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

GROUND_EMPTY = {
    "source": "ground_terminal",
    "connected": False,
    "updated": 0.0,
    "data": {},
}

INTERNAL_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Independent rescue dashboard server")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--output", type=Path, default=ROOT / "output")
    parser.add_argument("--web-dir", type=Path, default=WEB_DIR)
    return parser.parse_args()


def normalize_snapshot(loaded: object, empty: dict, stale_after: float) -> dict:
    value = dict(empty)
    if isinstance(loaded, dict):
        value.update(loaded)
    updated = float(value.get("updated") or 0.0)
    fresh = updated > 0 and time.time() - updated <= stale_after
    value["connected"] = bool(value.get("connected") and fresh)
    value["fresh"] = fresh
    if not value["connected"] and empty.get("source") == "vision":
        value.update(fps=0.0, people=0, confirmed=False, boxes=[])
    return value


def read_snapshot(path: Path, empty: dict, stale_after: float) -> dict:
    loaded: object = {}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        pass
    return normalize_snapshot(loaded, empty, stale_after)


def write_json_atomic(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, path)


class DashboardHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, address, handler, *, output_dir: Path, web_dir: Path):
        super().__init__(address, handler)
        self.output_dir = output_dir.resolve()
        self.web_dir = web_dir.resolve()
        self.public_access = os.environ.get("WEB_PUBLIC", "").lower() in {"1", "true", "yes"}
        self.access_log = os.environ.get("WEB_ACCESS_LOG", "").lower() in {"1", "true", "yes"}
        username = os.environ.get("WEB_USERNAME", "")
        password = os.environ.get("WEB_PASSWORD", "")
        encoded = base64.b64encode(f"{username}:{password}".encode()).decode()
        self.expected_authorization = f"Basic {encoded}"
        self.session_token = secrets.token_urlsafe(24)
        self.ground_token = os.environ.get("GROUND_INGEST_TOKEN", "")
        self.control_peer_token = os.environ.get("CONTROL_PEER_TOKEN", "")
        self.control_base_url = os.environ.get("FLIGHT_CONTROL_BASE_URL", "http://127.0.0.1:8091").rstrip("/")
        self.control_upstream_kind = os.environ.get("FLIGHT_CONTROL_UPSTREAM_KIND", "bridge").lower()
        self.video_url = os.environ.get("VIDEO_URL", "")
        self.video_health_url = os.environ.get("VIDEO_HEALTH_URL", "")
        self.air_unit_local = os.environ.get("AIR_UNIT_LOCAL", "").lower() in {"1", "true", "yes"}
        self.upstreams = {
            "vision": os.environ.get("VISION_UPSTREAM_URL", ""),
            "flight_controller": os.environ.get("FLIGHT_UPSTREAM_URL", ""),
            "ground_terminal": os.environ.get("GROUND_UPSTREAM_URL", ""),
        }


class DashboardHandler(BaseHTTPRequestHandler):
    server: DashboardHTTPServer
    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args) -> None:
        if self.server.access_log:
            print(f"[WEB] {self.address_string()} {format % args}")

    def send_body(self, status: int, body: bytes, content_type: str, *, session=False) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        if session:
            self.send_header(
                "Set-Cookie",
                f"dashboard_session={self.server.session_token}; Path=/; HttpOnly; SameSite=Strict",
            )
        self.end_headers()
        self.wfile.write(body)

    def send_json(self, status: int, value: dict, *, session=False) -> None:
        self.send_body(
            status,
            json.dumps(value, ensure_ascii=False).encode("utf-8"),
            "application/json; charset=utf-8",
            session=session,
        )

    def page_authorized(self) -> bool:
        if self.server.public_access:
            return True
        supplied = self.headers.get("Authorization", "")
        return hmac.compare_digest(supplied, self.server.expected_authorization)

    def control_session_valid(self) -> bool:
        peer = self.headers.get("X-Ground-Peer-Token", "")
        if self.server.control_peer_token and hmac.compare_digest(peer, self.server.control_peer_token):
            return True
        cookie = self.headers.get("Cookie", "")
        expected = f"dashboard_session={self.server.session_token}"
        return any(hmac.compare_digest(part.strip(), expected) for part in cookie.split(";"))

    def require_page_auth(self) -> bool:
        if self.page_authorized():
            return True
        self.send_response(HTTPStatus.UNAUTHORIZED)
        self.send_header("WWW-Authenticate", 'Basic realm="Rescue Dashboard"')
        self.send_header("Content-Length", "0")
        self.end_headers()
        return False

    def snapshot(self, filename: str, empty: dict, stale_after: float) -> dict:
        upstream = self.server.upstreams.get(str(empty.get("source")), "")
        if upstream:
            try:
                request = urllib.request.Request(upstream, headers={"Accept": "application/json"})
                with INTERNAL_OPENER.open(request, timeout=0.8) as response:
                    value = normalize_snapshot(json.load(response), empty, stale_after)
                    value["gateway_connected"] = True
                    return value
            except (urllib.error.URLError, TimeoutError, OSError, ValueError, TypeError):
                value = normalize_snapshot({}, empty, stale_after)
                value["gateway_connected"] = False
                return value
        value = read_snapshot(self.server.output_dir / filename, empty, stale_after)
        value["gateway_connected"] = self.server.air_unit_local
        return value

    def video_connected(self, fallback: bool) -> bool:
        if not self.server.video_health_url:
            return fallback
        try:
            request = urllib.request.Request(
                self.server.video_health_url,
                headers={"Accept": "application/vnd.apple.mpegurl", "Range": "bytes=0-512"},
            )
            with INTERNAL_OPENER.open(request, timeout=0.8) as response:
                return 200 <= response.status < 400
        except (urllib.error.URLError, TimeoutError, OSError, ValueError):
            return False

    def proxy_control(self, method: str, body: bytes = b"") -> None:
        if not self.control_session_valid():
            self.send_json(HTTPStatus.FORBIDDEN, {"ok": False, "error": "invalid_session"})
            return
        control_pin = self.headers.get("X-Control-Pin", "")
        if method == "POST" and body and not control_pin:
            try:
                value = json.loads(body)
                if isinstance(value, dict):
                    control_pin = str(value.pop("pin", ""))
                    body = json.dumps(value, ensure_ascii=False).encode("utf-8")
            except (ValueError, TypeError, json.JSONDecodeError):
                pass
        headers = {"Content-Type": "application/json", "X-Control-Pin": control_pin}
        if self.server.control_peer_token:
            headers["X-Ground-Peer-Token"] = self.server.control_peer_token
        bridge_paths = {"/api/control/status": "/status", "/api/flight-command": "/command"}
        target_path = self.path if self.server.control_upstream_kind == "dashboard" else bridge_paths.get(self.path, self.path)
        request = urllib.request.Request(
            self.server.control_base_url + target_path,
            data=body if method == "POST" else None,
            method=method,
            headers=headers,
        )
        try:
            with INTERNAL_OPENER.open(request, timeout=1.0) as response:
                payload = response.read(65536)
                self.send_body(response.status, payload, "application/json; charset=utf-8", session=True)
        except urllib.error.HTTPError as error:
            self.send_body(error.code, error.read(65536), "application/json; charset=utf-8", session=True)
        except (urllib.error.URLError, TimeoutError, OSError):
            self.send_json(
                HTTPStatus.SERVICE_UNAVAILABLE,
                {"ok": False, "enabled": False, "error": "flight_control_offline"},
                session=True,
            )

    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0]
        if path == "/api/config":
            self.send_json(HTTPStatus.OK, {"video_url": self.server.video_url})
            return
        if path == "/status.json":
            self.send_json(HTTPStatus.OK, self.snapshot("detection_status.json", VISION_EMPTY, 3.0))
            return
        if path == "/telemetry.json":
            self.send_json(HTTPStatus.OK, self.snapshot("flight_telemetry.json", FLIGHT_EMPTY, 3.0))
            return
        if path == "/ground.json":
            self.send_json(HTTPStatus.OK, self.snapshot("ground_terminal.json", GROUND_EMPTY, 15.0))
            return
        if path == "/api/sources":
            vision = self.snapshot("detection_status.json", VISION_EMPTY, 3.0)
            flight = self.snapshot("flight_telemetry.json", FLIGHT_EMPTY, 3.0)
            ground = self.snapshot("ground_terminal.json", GROUND_EMPTY, 15.0)
            air_unit_connected = bool(vision.get("gateway_connected") or flight.get("gateway_connected"))
            video_connected = air_unit_connected and self.video_connected(bool(vision["connected"]))
            self.send_json(HTTPStatus.OK, {
                "platform": {"connected": True},
                "air_unit": {"connected": air_unit_connected},
                "vision": {"connected": vision["connected"], "updated": vision.get("updated", 0)},
                "flight": {"connected": flight["connected"], "updated": flight.get("updated", 0)},
                "video": {"connected": video_connected},
                "ground": {"connected": ground["connected"], "updated": ground.get("updated", 0)},
                "updated": time.time(),
            })
            return
        if path == "/api/control/status":
            self.proxy_control("GET")
            return

        static_files = {
            "/": "index.html",
            "/index.html": "index.html",
            "/assets/dashboard.css": "dashboard.css",
            "/assets/dashboard.js": "dashboard.js",
        }
        filename = static_files.get(path)
        if filename is None:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        if not self.require_page_auth():
            return
        try:
            body = (self.server.web_dir / filename).read_bytes()
        except OSError:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        if content_type.startswith("text/") or content_type == "application/javascript":
            content_type += "; charset=utf-8"
        self.send_body(HTTPStatus.OK, body, content_type, session=True)

    def do_POST(self) -> None:
        path = self.path.split("?", 1)[0]
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = -1
        if length < 0 or length > 65536:
            self.send_json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {"ok": False, "error": "invalid_size"})
            return
        body = self.rfile.read(length)
        if path == "/api/flight-command":
            self.proxy_control("POST", body)
            return
        if path == "/api/ingest/ground":
            expected = f"Bearer {self.server.ground_token}"
            supplied = self.headers.get("Authorization", "")
            if not self.server.ground_token:
                self.send_json(HTTPStatus.SERVICE_UNAVAILABLE, {"ok": False, "error": "ingest_not_configured"})
                return
            if not hmac.compare_digest(supplied, expected):
                self.send_json(HTTPStatus.UNAUTHORIZED, {"ok": False, "error": "unauthorized"})
                return
            try:
                value = json.loads(body)
                if not isinstance(value, dict):
                    raise ValueError
            except (ValueError, TypeError):
                self.send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "invalid_json"})
                return
            value.update(source="ground_terminal", connected=True, updated=time.time())
            write_json_atomic(self.server.output_dir / "ground_terminal.json", value)
            self.send_json(HTTPStatus.OK, {"ok": True})
            return
        self.send_error(HTTPStatus.NOT_FOUND)


def create_server(host: str, port: int, output_dir: Path, web_dir: Path) -> DashboardHTTPServer:
    return DashboardHTTPServer((host, port), DashboardHandler, output_dir=output_dir, web_dir=web_dir)


def main() -> int:
    args = parse_args()
    server = create_server(args.host, args.port, args.output, args.web_dir)
    print(f"[INFO] Independent dashboard listening on http://{args.host}:{args.port}")
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
