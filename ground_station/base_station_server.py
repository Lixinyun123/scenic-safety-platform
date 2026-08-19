"""Ground-station target and mission service.

The service is deliberately independent from cameras and aircraft hardware.
Ground detection devices report heartbeats and coordinates here. Operators can
confirm a target and prepare a mission, while aircraft dispatch remains a
separate, explicitly gated integration step.
"""

from __future__ import annotations

import argparse
import hmac
import json
import os
import threading
import time
import uuid
import mimetypes
import urllib.error
import urllib.request
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Rescue base-station service")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8090)
    parser.add_argument("--data-dir", type=Path, default=Path(__file__).resolve().parent / "data")
    return parser.parse_args()


def _number(value: object, minimum: float, maximum: float, name: str) -> float:
    if isinstance(value, bool):
        raise ValueError(name)
    result = float(value)
    if not minimum <= result <= maximum:
        raise ValueError(name)
    return result


def _text(value: object, name: str, limit: int = 64) -> str:
    result = str(value or "").strip()
    if not result or len(result) > limit:
        raise ValueError(name)
    return result


def atomic_write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


class BaseStationState:
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir.resolve()
        self.state_path = self.data_dir / "base_station_state.json"
        self.event_path = self.data_dir / "base_station_events.jsonl"
        self.lock = threading.RLock()
        self.state = {"devices": {}, "targets": [], "mission": None, "updated": time.time()}
        try:
            loaded = json.loads(self.state_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                self.state.update(loaded)
        except (OSError, ValueError, TypeError):
            pass

    def _save(self, event: str, detail: dict) -> None:
        self.state["updated"] = time.time()
        atomic_write(self.state_path, self.state)
        self.event_path.parent.mkdir(parents=True, exist_ok=True)
        record = {"event": event, "time": time.time(), **detail}
        with self.event_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")

    def snapshot(self) -> dict:
        with self.lock:
            value = json.loads(json.dumps(self.state))
        now = time.time()
        for device in value["devices"].values():
            device["connected"] = now - float(device.get("updated") or 0) <= 15.0
        value["connected_devices"] = sum(1 for item in value["devices"].values() if item["connected"])
        value["pending_targets"] = sum(1 for item in value["targets"] if item["status"] == "detected")
        return value

    def ingest(self, payload: dict) -> dict:
        device_id = _text(payload.get("device_id"), "device_id")
        now = time.time()
        device = {
            "device_id": device_id,
            "name": str(payload.get("name") or device_id)[:80],
            "latitude": None,
            "longitude": None,
            "battery_percent": None,
            "health": str(payload.get("health") or "normal")[:32],
            "updated": now,
        }
        if payload.get("latitude") is not None and payload.get("longitude") is not None:
            device["latitude"] = _number(payload["latitude"], -90, 90, "latitude")
            device["longitude"] = _number(payload["longitude"], -180, 180, "longitude")
        if payload.get("battery_percent") is not None:
            device["battery_percent"] = _number(payload["battery_percent"], 0, 100, "battery_percent")

        accepted = []
        targets = payload.get("targets") or []
        if not isinstance(targets, list) or len(targets) > 20:
            raise ValueError("targets")
        with self.lock:
            self.state["devices"][device_id] = device
            for supplied in targets:
                if not isinstance(supplied, dict):
                    raise ValueError("target")
                target = {
                    "target_id": uuid.uuid4().hex[:12],
                    "device_id": device_id,
                    "latitude": _number(supplied.get("latitude"), -90, 90, "target.latitude"),
                    "longitude": _number(supplied.get("longitude"), -180, 180, "target.longitude"),
                    "confidence": _number(supplied.get("confidence", 0), 0, 1, "target.confidence"),
                    "status": "detected",
                    "observed_at": float(supplied.get("observed_at") or now),
                    "created_at": now,
                }
                self.state["targets"].append(target)
                accepted.append(target["target_id"])
            self.state["targets"] = self.state["targets"][-200:]
            self._save("device_ingest", {"device_id": device_id, "target_ids": accepted})
        return {"ok": True, "device_id": device_id, "target_ids": accepted}

    def confirm_target(self, target_id: str) -> dict:
        with self.lock:
            target = next((item for item in self.state["targets"] if item["target_id"] == target_id), None)
            if target is None:
                raise KeyError("target_not_found")
            if target["status"] not in {"detected", "confirmed"}:
                raise RuntimeError("target_not_confirmable")
            target["status"] = "confirmed"
            target["confirmed_at"] = time.time()
            self._save("target_confirmed", {"target_id": target_id})
            return dict(target)

    def prepare_mission(self, target_id: str, aircraft_id: str) -> dict:
        aircraft_id = _text(aircraft_id, "aircraft_id")
        with self.lock:
            target = next((item for item in self.state["targets"] if item["target_id"] == target_id), None)
            if target is None:
                raise KeyError("target_not_found")
            if target["status"] != "confirmed":
                raise RuntimeError("target_not_confirmed")
            mission = {
                "mission_id": uuid.uuid4().hex[:12],
                "target_id": target_id,
                "aircraft_id": aircraft_id,
                "latitude": target["latitude"],
                "longitude": target["longitude"],
                "status": "prepared",
                "dispatch_enabled": False,
                "created_at": time.time(),
            }
            self.state["mission"] = mission
            self._save("mission_prepared", {"mission_id": mission["mission_id"], "target_id": target_id})
            return dict(mission)

    def dispatch_mission(self, mission_id: str) -> dict:
        """Place a prepared mission in the aircraft task queue.

        Dispatching records operator intent and makes the mission visible to
        the aircraft workspace. Actual waypoint execution remains gated by the
        flight-control bridge; the web layer must never pretend that takeoff or
        navigation has happened before the aircraft acknowledges it.
        """
        with self.lock:
            mission = self.state.get("mission")
            if not isinstance(mission, dict) or mission.get("mission_id") != mission_id:
                raise KeyError("mission_not_found")
            if mission.get("status") not in {"prepared", "queued"}:
                raise RuntimeError("mission_not_dispatchable")
            mission["status"] = "queued"
            mission["dispatch_enabled"] = True
            mission["dispatched_at"] = time.time()
            self._save("mission_dispatched", {"mission_id": mission_id})
            return dict(mission)


class BaseStationServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, address, handler, *, data_dir: Path):
        super().__init__(address, handler)
        self.store = BaseStationState(data_dir)
        self.ingest_token = os.environ.get("BASE_INGEST_TOKEN", "")
        self.operator_token = os.environ.get("BASE_OPERATOR_TOKEN", "")
        self.drone_dashboard_url = os.environ.get(
            "DRONE_DASHBOARD_URL", "http://192.168.1.123:8080"
        ).rstrip("/")
        self.drone_peer_token = os.environ.get("DRONE_CONTROL_PEER_TOKEN", "")
        self.station_video_url = os.environ.get(
            "STATION_VIDEO_URL",
            "http://192.168.1.202:8889/station?controls=false&muted=true&autoplay=true&playsInline=true",
        )
        self.station_video_health_url = os.environ.get("STATION_VIDEO_HEALTH_URL", "")
        self.drone_video_url = os.environ.get("DRONE_VIDEO_URL", "")
        self.drone_video_health_url = os.environ.get("DRONE_VIDEO_HEALTH_URL", "")
        # A cloud deployment must not become a public flight-control relay by
        # accident.  This is deliberately opt-in and is only enabled after a
        # trusted ground gateway has been connected to the server.
        self.allow_flight_proxy = os.environ.get("ALLOW_FLIGHT_PROXY", "false").lower() in {
            "1", "true", "yes", "on"
        }
        # Local camera/flight-control traffic must never be sent through the
        # machine's Internet HTTP proxy.  A configured proxy previously made
        # healthy 192.168.x.x endpoints appear as 503/offline.
        self.local_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))


class BaseStationHandler(BaseHTTPRequestHandler):
    server: BaseStationServer
    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args) -> None:
        return

    def send_json(self, status: int, value: dict) -> None:
        body = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def send_static(self, path: Path) -> None:
        try:
            body = path.read_bytes()
        except OSError:
            self.send_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "not_found"})
            return
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type + ("; charset=utf-8" if content_type.startswith("text/") else ""))
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def bearer_valid(self, expected: str) -> bool:
        supplied = self.headers.get("Authorization", "")
        return bool(expected) and hmac.compare_digest(supplied, f"Bearer {expected}")

    def read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if length < 0 or length > 65536:
            raise ValueError("invalid_size")
        value = json.loads(self.rfile.read(length))
        if not isinstance(value, dict):
            raise ValueError("invalid_json")
        return value

    def upstream_request(self, path: str, *, method: str = "GET", body=None) -> None:
        headers = {"Accept": "application/json"}
        if body is not None:
            headers["Content-Type"] = "application/json"
        if self.server.drone_peer_token:
            headers["X-Ground-Peer-Token"] = self.server.drone_peer_token
        request = urllib.request.Request(
            self.server.drone_dashboard_url + path,
            data=body,
            method=method,
            headers=headers,
        )
        try:
            with self.server.local_opener.open(request, timeout=1.2) as response:
                payload = response.read(65536)
                self.send_response(response.status)
                self.send_header("Content-Type", response.headers.get("Content-Type", "application/json"))
                self.send_header("Content-Length", str(len(payload)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(payload)
        except urllib.error.HTTPError as error:
            payload = error.read(65536)
            self.send_response(error.code)
            self.send_header("Content-Type", error.headers.get("Content-Type", "application/json"))
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(payload)
        except (urllib.error.URLError, TimeoutError, OSError):
            self.send_json(
                HTTPStatus.SERVICE_UNAVAILABLE,
                {"ok": False, "connected": False, "error": "drone_platform_offline"},
            )

    @staticmethod
    def video_kind(url: str) -> str:
        lowered = url.lower().split("?", 1)[0]
        if lowered.endswith(".m3u8"):
            return "hls"
        if lowered.endswith((".mjpg", ".mjpeg", ".jpg", ".jpeg")):
            return "image"
        return "embed"

    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0]
        web_root = Path(__file__).resolve().parent / "web"
        static_files = {
            "/": web_root / "index.html",
            "/index.html": web_root / "index.html",
            "/styles.css": web_root / "styles.css",
            "/accessibility.css": web_root / "accessibility.css",
            "/map.js": web_root / "map.js",
            "/platform.js": web_root / "platform.js",
            "/runtime-config.js": web_root / "runtime-config.js",
            "/vendor/leaflet/leaflet.css": web_root / "vendor" / "leaflet" / "leaflet.css",
            "/vendor/leaflet/leaflet.js": web_root / "vendor" / "leaflet" / "leaflet.js",
            "/assets/scenic-monitor-demo.png": web_root / "assets" / "scenic-monitor-demo.png",
            "/assets/drone-monitor-demo.png": web_root / "assets" / "drone-monitor-demo.png",
            "/drone/": web_root.parent.parent / "raspberry_pi_vision" / "web" / "index.html",
            "/drone/index.html": web_root.parent.parent / "raspberry_pi_vision" / "web" / "index.html",
            "/drone/assets/dashboard.css": web_root.parent.parent / "raspberry_pi_vision" / "web" / "dashboard.css",
            "/drone/assets/dashboard.js": web_root.parent.parent / "raspberry_pi_vision" / "web" / "dashboard.js",
        }
        if path in static_files:
            self.send_static(static_files[path])
            return
        if path == "/api/base/status":
            self.send_json(HTTPStatus.OK, self.server.store.snapshot())
            return
        if path == "/api/platform/config":
            drone_video_url = self.server.drone_video_url
            if not drone_video_url:
                request = urllib.request.Request(
                    self.server.drone_dashboard_url + "/api/config",
                    headers={"Accept": "application/json"},
                )
                try:
                    with self.server.local_opener.open(request, timeout=1.2) as response:
                        upstream_config = json.loads(response.read(65536))
                    drone_video_url = str(upstream_config.get("video_url", "")).strip()
                except (urllib.error.URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError):
                    drone_video_url = ""
            self.send_json(HTTPStatus.OK, {
                "station_video": {
                    "url": self.server.station_video_url,
                    "kind": self.video_kind(self.server.station_video_url),
                    "configured": bool(self.server.station_video_url),
                },
                "drone_video": {
                    "url": drone_video_url,
                    "kind": self.video_kind(drone_video_url),
                    "configured": bool(drone_video_url),
                },
                "drone_dashboard_url": self.server.drone_dashboard_url,
            })
            return
        if path in {"/status.json", "/telemetry.json", "/ground.json", "/api/sources", "/api/config", "/api/control/status"}:
            self.upstream_request(path)
            return
        self.send_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "not_found"})

    def do_POST(self) -> None:
        path = self.path.split("?", 1)[0]
        if path == "/api/flight-command":
            if not self.server.allow_flight_proxy:
                self.send_json(
                    HTTPStatus.SERVICE_UNAVAILABLE,
                    {
                        "ok": False,
                        "enabled": False,
                        "error": "flight_gateway_not_enabled",
                    },
                )
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                length = -1
            if length < 0 or length > 65536:
                self.send_json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {"ok": False, "error": "invalid_size"})
                return
            self.upstream_request(path, method="POST", body=self.rfile.read(length))
            return
        if path == "/api/base/ingest":
            if not self.bearer_valid(self.server.ingest_token):
                self.send_json(HTTPStatus.UNAUTHORIZED, {"ok": False, "error": "unauthorized"})
                return
            try:
                result = self.server.store.ingest(self.read_json())
            except (ValueError, TypeError, json.JSONDecodeError):
                self.send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "invalid_payload"})
                return
            self.send_json(HTTPStatus.OK, result)
            return

        if not self.bearer_valid(self.server.operator_token):
            self.send_json(HTTPStatus.UNAUTHORIZED, {"ok": False, "error": "unauthorized"})
            return
        try:
            payload = self.read_json()
            if path.startswith("/api/base/targets/") and path.endswith("/confirm"):
                prefix = "/api/base/targets/"
                suffix = "/confirm"
                target_id = path[len(prefix):-len(suffix)].strip("/")
                value = self.server.store.confirm_target(target_id)
                self.send_json(HTTPStatus.OK, {"ok": True, "target": value})
                return
            if path == "/api/base/missions/prepare":
                value = self.server.store.prepare_mission(
                    _text(payload.get("target_id"), "target_id"),
                    _text(payload.get("aircraft_id"), "aircraft_id"),
                )
                self.send_json(HTTPStatus.OK, {"ok": True, "mission": value})
                return
            if path == "/api/base/missions/dispatch":
                value = self.server.store.dispatch_mission(
                    _text(payload.get("mission_id"), "mission_id")
                )
                self.send_json(HTTPStatus.OK, {"ok": True, "mission": value})
                return
        except KeyError as error:
            self.send_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": str(error.args[0])})
            return
        except RuntimeError as error:
            self.send_json(HTTPStatus.CONFLICT, {"ok": False, "error": str(error)})
            return
        except (ValueError, TypeError, json.JSONDecodeError):
            self.send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "invalid_payload"})
            return
        self.send_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "not_found"})


def create_server(host: str, port: int, data_dir: Path) -> BaseStationServer:
    return BaseStationServer((host, port), BaseStationHandler, data_dir=data_dir)


def main() -> int:
    args = parse_args()
    server = create_server(args.host, args.port, args.data_dir)
    print(f"[BASE] listening on http://{args.host}:{args.port}")
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
