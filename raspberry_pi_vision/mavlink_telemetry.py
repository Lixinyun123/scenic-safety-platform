"""MAVLink telemetry and safety-gated bench-control bridge for Pixhawk USB."""

from __future__ import annotations

import argparse
import glob
import hmac
import json
import math
import os
import queue
import select
import struct
import termios
import threading
import time
import tty
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


GPS_FIX_NAMES = {
    0: "无GPS",
    1: "未定位",
    2: "2D定位",
    3: "3D定位",
    4: "DGPS",
    5: "RTK浮点",
    6: "RTK固定",
}

COPTER_MODES = {
    0: "STABILIZE", 1: "ACRO", 2: "ALT_HOLD", 3: "AUTO", 4: "GUIDED",
    5: "LOITER", 6: "RTL", 7: "CIRCLE", 9: "LAND", 11: "DRIFT",
    13: "SPORT", 14: "FLIP", 15: "AUTOTUNE", 16: "POSHOLD",
    17: "BRAKE", 18: "THROW", 20: "GUIDED_NOGPS", 21: "SMART_RTL",
    22: "FLOWHOLD", 23: "FOLLOW", 24: "ZIGZAG", 26: "AUTOROTATE",
}

PLANE_MODES = {
    0: "MANUAL", 1: "CIRCLE", 2: "STABILIZE", 3: "TRAINING", 4: "ACRO",
    5: "FBWA", 6: "FBWB", 7: "CRUISE", 8: "AUTOTUNE", 10: "AUTO",
    11: "RTL", 12: "LOITER", 13: "TAKEOFF", 15: "GUIDED",
    17: "QSTABILIZE", 18: "QHOVER", 19: "QLOITER", 20: "QLAND",
    21: "QRTL", 22: "QAUTOTUNE", 23: "QACRO",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Read-only MAVLink telemetry")
    parser.add_argument("--connection", default="auto")
    parser.add_argument("--baud", type=int, default=115200)
    parser.add_argument("--output", default="output/flight_telemetry.json")
    parser.add_argument("--control-host", default="127.0.0.1")
    parser.add_argument("--control-port", type=int, default=8091)
    return parser.parse_args()


def empty_state() -> dict:
    return {
        "connected": False,
        "device": None,
        "vehicle_profile": "unknown",
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
        "gps_fix_type": None,
        "flight_mode": None,
        "armed": None,
        "system_status": None,
        "ekf_flags": 0,
        "sensor_health": {
            "gyroscope": None,
            "accelerometer": None,
            "barometer": None,
            "gps": None,
        },
        "flight_message": None,
        "command_result": None,
        "updated": 0.0,
    }


def write_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, path)


class MavlinkParser:
    def __init__(self) -> None:
        self.buffer = bytearray()

    def feed(self, data: bytes):
        self.buffer.extend(data)
        frames = []
        while self.buffer:
            positions = [
                p
                for p in (self.buffer.find(b"\xfd"), self.buffer.find(b"\xfe"))
                if p >= 0
            ]
            if not positions:
                self.buffer.clear()
                break
            start = min(positions)
            if start:
                del self.buffer[:start]
            magic = self.buffer[0]
            if magic == 0xFD:
                if len(self.buffer) < 10:
                    break
                payload_length = self.buffer[1]
                signed = bool(self.buffer[2] & 0x01)
                frame_length = 10 + payload_length + 2 + (13 if signed else 0)
                if len(self.buffer) < frame_length:
                    break
                system_id = self.buffer[5]
                component_id = self.buffer[6]
                message_id = self.buffer[7] | self.buffer[8] << 8 | self.buffer[9] << 16
                payload = bytes(self.buffer[10 : 10 + payload_length])
            else:
                if len(self.buffer) < 6:
                    break
                payload_length = self.buffer[1]
                frame_length = 6 + payload_length + 2
                if len(self.buffer) < frame_length:
                    break
                system_id = self.buffer[3]
                component_id = self.buffer[4]
                message_id = self.buffer[5]
                payload = bytes(self.buffer[6 : 6 + payload_length])
            frames.append((message_id, payload, system_id, component_id))
            del self.buffer[:frame_length]
        return frames


def mode_name(vehicle_type: int, custom_mode: int) -> str:
    if vehicle_type == 1:
        return PLANE_MODES.get(custom_mode, f"MODE_{custom_mode}")
    if vehicle_type in {2, 3, 4, 13, 14, 15, 29}:
        return COPTER_MODES.get(custom_mode, f"MODE_{custom_mode}")
    return f"MODE_{custom_mode}"


MAV_RESULT_NAMES = {
    0: "accepted", 1: "temporarily_rejected", 2: "denied", 3: "unsupported",
    4: "failed", 5: "in_progress", 6: "cancelled",
}


def vehicle_profile_for_device(device: str | None) -> str:
    name = os.path.basename(device or "")
    gps_baro_ids = {
        value.strip()
        for value in os.environ.get("GPS_BARO_DEVICE_IDS", "").split(",")
        if value.strip()
    }
    optical_flow_ids = {
        value.strip()
        for value in os.environ.get("OPTICAL_FLOW_DEVICE_IDS", "").split(",")
        if value.strip()
    }
    if any(value in name for value in gps_baro_ids):
        return "gps_baro"
    if any(value in name for value in optical_flow_ids):
        return "optical_flow"
    return "unknown"


def preflight_checks(state: dict) -> dict[str, bool]:
    connected = bool(state.get("connected"))
    system_ready = int(state.get("system_status") or 0) in {3, 4}
    battery = connected and float(state.get("battery_percent") or 0) >= 30
    profile = state.get("vehicle_profile")
    health = state.get("sensor_health") or {}
    if profile == "gps_baro":
        ekf_flags = int(state.get("ekf_flags") or 0)
        ekf_position_ready = bool(ekf_flags & 16) and not bool(ekf_flags & 1024)
        navigation = (
            connected
            and int(state.get("gps_fix_type") or 0) >= 3
            and int(state.get("satellites") or 0) >= 6
            and health.get("gps") is True
            and ekf_position_ready
        )
        altitude = connected and health.get("barometer") is True
    elif profile == "optical_flow":
        navigation = connected and int(state.get("optical_flow_quality") or 0) >= 50
        altitude = (
            connected
            and state.get("height_agl") is not None
            and time.time() - float(state.get("range_updated") or 0) < 2
        )
    else:
        navigation = False
        altitude = False
    return {
        "flight_controller": connected and system_ready,
        "battery": battery,
        "navigation": navigation,
        "altitude": altitude,
    }


class ControlBridge:
    """Localhost-only command queue; the serial loop remains the sole MAVLink owner."""

    def __init__(self, state: dict) -> None:
        self.state = state
        self.pin = os.environ.get("FLIGHT_CONTROL_PIN", "")
        self.enabled = os.environ.get("FLIGHT_CONTROL_ENABLED", "0").lower() in {"1", "true", "yes"}
        self.takeoff_enabled = os.environ.get("FLIGHT_TAKEOFF_ENABLED", "0").lower() in {"1", "true", "yes"}
        self.commands: queue.Queue[dict] = queue.Queue(maxsize=4)
        self.last_control_heartbeat = 0.0
        self.pending: dict | None = None
        self.lock = threading.Lock()

    def authorized(self, supplied: str) -> bool:
        return bool(self.enabled and self.pin and hmac.compare_digest(supplied, self.pin))

    def status(self) -> dict:
        with self.lock:
            pending = None if self.pending is None else self.pending.get("action")
        return {
            "enabled": bool(self.enabled and self.pin),
            "takeoff_enabled": self.takeoff_enabled,
            "pending": pending,
            "control_heartbeat": time.monotonic() - self.last_control_heartbeat < 3,
            "vehicle_profile": self.state.get("vehicle_profile", "unknown"),
            "preflight": preflight_checks(self.state),
        }

    def submit(self, action: str, params: dict, pin: str) -> tuple[int, dict]:
        if not self.authorized(pin):
            return 403, {"ok": False, "error": "控制PIN错误或控制服务未启用"}
        self.last_control_heartbeat = time.monotonic()
        if action == "heartbeat":
            return 200, {"ok": True, "status": self.status()}
        if action not in {"arm", "disarm", "set_mode", "takeoff"}:
            return 400, {"ok": False, "error": "不支持的飞行指令"}
        if not self.state.get("connected"):
            return 409, {"ok": False, "error": "飞控未连接"}
        if action == "takeoff" and not self.takeoff_enabled:
            return 423, {"ok": False, "error": "台架模式禁止起飞"}
        if action == "arm":
            if not all(preflight_checks(self.state).values()) or self.state.get("armed") is not False:
                return 409, {"ok": False, "error": "基础自检未通过，拒绝解锁"}
        if action == "takeoff":
            if self.state.get("armed") is not True:
                return 409, {"ok": False, "error": "aircraft is not armed"}
            if not all(preflight_checks(self.state).values()):
                return 409, {"ok": False, "error": "preflight checks are not complete"}
            if self.state.get("flight_mode") != "GUIDED":
                return 409, {"ok": False, "error": "switch to GUIDED mode before takeoff"}
        request = {"action": action, "params": params, "event": threading.Event(), "result": None}
        try:
            self.commands.put_nowait(request)
        except queue.Full:
            return 429, {"ok": False, "error": "已有指令正在执行"}
        if not request["event"].wait(4.0):
            return 504, {"ok": False, "error": "飞控指令确认超时"}
        result = request["result"] or {"ok": False, "error": "未知指令结果"}
        return (200 if result.get("ok") else 409), result


def start_control_server(bridge: ControlBridge, host: str, port: int) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def send_json(self, status: int, value: dict) -> None:
            body = json.dumps(value, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            if self.path != "/status":
                self.send_error(404)
                return
            self.send_json(200, bridge.status())

        def do_POST(self) -> None:
            if self.path != "/command":
                self.send_error(404)
                return
            try:
                length = min(int(self.headers.get("Content-Length", "0")), 1024)
                value = json.loads(self.rfile.read(length) or b"{}")
                action = str(value.get("action", ""))
                params = value.get("params") if isinstance(value.get("params"), dict) else {}
                status, result = bridge.submit(action, params, self.headers.get("X-Control-Pin", ""))
            except (ValueError, json.JSONDecodeError):
                status, result = 400, {"ok": False, "error": "无效请求"}
            self.send_json(status, result)

        def log_message(self, _format: str, *_args) -> None:
            return

    server = ThreadingHTTPServer((host, port), Handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True, name="flight-control-api").start()
    return server


def update_from_message(state: dict, message_id: int, payload: bytes) -> bool:
    try:
        if message_id == 0 and len(payload) >= 9:  # HEARTBEAT
            custom_mode = struct.unpack_from("<I", payload, 0)[0]
            vehicle_type = payload[4]
            base_mode = payload[6]
            state["system_status"] = payload[7]
            state["flight_mode"] = mode_name(vehicle_type, custom_mode)
            state["armed"] = bool(base_mode & 0x80)
            return True
        if message_id == 33 and len(payload) >= 28:  # GLOBAL_POSITION_INT
            lat, lon, _alt, relative_alt = struct.unpack_from("<iiii", payload, 4)
            vx, vy = struct.unpack_from("<hh", payload, 20)
            heading = struct.unpack_from("<H", payload, 26)[0]
            if lat or lon:
                state["latitude"] = lat / 1e7
                state["longitude"] = lon / 1e7
            state["relative_altitude"] = round(relative_alt / 1000, 2)
            state["ground_speed"] = round(math.hypot(vx, vy) / 100, 2)
            if heading != 65535:
                state["heading"] = round(heading / 100, 1)
        elif message_id == 24 and len(payload) >= 30:  # GPS_RAW_INT
            fix_type = payload[28]
            state["gps_fix_type"] = fix_type
            state["satellites"] = payload[29]
            state["gps_fix"] = GPS_FIX_NAMES.get(fix_type, str(fix_type))
        elif message_id == 1 and len(payload) >= 31:  # SYS_STATUS
            present, enabled, healthy = struct.unpack_from("<III", payload, 0)
            sensor_health = state["sensor_health"]
            for name, mask in {
                "gyroscope": 1,
                "accelerometer": 2,
                "barometer": 8,
                "gps": 32,
            }.items():
                sensor_health[name] = bool(present & mask and enabled & mask and healthy & mask)
            voltage = struct.unpack_from("<H", payload, 14)[0]
            remaining = struct.unpack_from("<b", payload, 30)[0]
            if 1000 <= voltage < 65535:
                state["battery_voltage"] = round(voltage / 1000, 2)
            if remaining >= 0:
                state["battery_percent"] = remaining
        elif message_id == 74 and len(payload) >= 20:  # VFR_HUD fallback
            ground_speed = struct.unpack_from("<f", payload, 4)[0]
            heading = struct.unpack_from("<h", payload, 8)[0]
            state["ground_speed"] = round(ground_speed, 2)
            state["heading"] = float(heading % 360)
        elif message_id == 100 and len(payload) >= 26:  # OPTICAL_FLOW
            state["optical_flow_quality"] = payload[25]
        elif message_id == 132 and len(payload) >= 13:  # DISTANCE_SENSOR
            minimum, maximum, current = struct.unpack_from("<HHH", payload, 4)
            orientation = payload[12]
            # MAV_SENSOR_ROTATION_PITCH_270 (25) is a downward-facing sensor.
            if orientation == 25 and current != 65535 and minimum <= current <= maximum:
                state["height_agl"] = round(current / 100, 2)
                state["height_source"] = "downward_rangefinder"
                state["range_updated"] = time.time()
        elif message_id == 147 and len(payload) >= 36:  # BATTERY_STATUS
            remaining = struct.unpack_from("<b", payload, 35)[0]
            if remaining >= 0:
                state["battery_percent"] = remaining
        elif message_id == 193 and len(payload) >= 22:  # EKF_STATUS_REPORT
            state["ekf_flags"] = struct.unpack_from("<H", payload, 20)[0]
        elif message_id == 253 and len(payload) >= 2:  # STATUSTEXT
            text = payload[1:51].split(b"\0", 1)[0].decode("utf-8", "replace").strip()
            if text:
                state["flight_message"] = text
    except (IndexError, struct.error):
        pass
    return False


def x25_crc(data: bytes, extra: int) -> int:
    crc = 0xFFFF
    for value in data + bytes((extra,)):
        temporary = value ^ (crc & 0xFF)
        temporary = (temporary ^ (temporary << 4)) & 0xFF
        crc = (
            (crc >> 8)
            ^ (temporary << 8)
            ^ (temporary << 3)
            ^ (temporary >> 4)
        ) & 0xFFFF
    return crc


def send_mavlink_v1(fd: int, sequence: int, message_id: int, payload: bytes, crc_extra: int) -> int:
    header = bytes((len(payload), sequence & 0xFF, 255, 190, message_id))
    checksum = x25_crc(header + payload, crc_extra)
    os.write(fd, b"\xfe" + header + payload + struct.pack("<H", checksum))
    return (sequence + 1) & 0xFF


def request_all_streams(fd: int, sequence: int, rate_hz: int = 4) -> None:
    # MAVLink v1 REQUEST_DATA_STREAM (ID 66, CRC extra 148).
    # target_system=1, target_component=1, stream=ALL(0), start=1.
    payload = struct.pack("<HBBBB", rate_hz, 1, 1, 0, 1)
    send_mavlink_v1(fd, sequence, 66, payload, 148)


def send_gcs_heartbeat(fd: int, sequence: int) -> int:
    payload = struct.pack("<IBBBBB", 0, 6, 8, 0, 4, 3)
    return send_mavlink_v1(fd, sequence, 0, payload, 50)


def send_command_long(fd: int, sequence: int, command: int, params: list[float]) -> int:
    values = (params + [0.0] * 7)[:7]
    payload = struct.pack("<7fHBBB", *values, command, 1, 1, 0)
    return send_mavlink_v1(fd, sequence, 76, payload, 152)


def open_serial(path: str, baud: int) -> int:
    fd = os.open(path, os.O_RDWR | os.O_NONBLOCK | os.O_NOCTTY)
    tty.setraw(fd)
    attrs = termios.tcgetattr(fd)
    speed = getattr(termios, f"B{baud}", termios.B115200)
    attrs[4] = speed
    attrs[5] = speed
    attrs[2] |= termios.CLOCAL | termios.CREAD
    termios.tcsetattr(fd, termios.TCSANOW, attrs)
    return fd


def serial_path_matches_fd(path: str, fd: int) -> bool:
    """Return false when a USB reconnect moved the stable symlink to a new tty."""
    try:
        return os.stat(path).st_rdev == os.fstat(fd).st_rdev
    except OSError:
        return False


def discover_serial_candidates() -> list[str]:
    """Find likely flight-controller ports, preferring stable USB IDs."""
    patterns = (
        "/dev/serial/by-id/usb-ArduPilot*",
        "/dev/serial/by-id/*Pixhawk*",
        "/dev/serial/by-id/*PX4*",
        "/dev/serial/by-id/*fmuv*",
    )
    stable = sorted({path for pattern in patterns for path in glob.glob(pattern)})
    candidates = stable or sorted(glob.glob("/dev/ttyACM*") + glob.glob("/dev/ttyUSB*"))
    unique: dict[str, str] = {}
    for path in candidates:
        unique.setdefault(os.path.realpath(path), path)
    return list(unique.values())


def resolve_serial_path(requested: str, candidates: list[str] | None = None) -> str:
    if requested.lower() != "auto":
        return requested
    available = discover_serial_candidates() if candidates is None else candidates
    unique: dict[str, str] = {}
    for path in available:
        unique.setdefault(os.path.realpath(path), path)
    selected = list(unique.values())
    if not selected:
        raise FileNotFoundError("no Pixhawk/ArduPilot serial device found")
    if len(selected) > 1:
        raise RuntimeError(f"multiple flight controllers found: {', '.join(selected)}")
    return selected[0]


def reset_vehicle_state(state: dict, device: str | None = None) -> None:
    state.clear()
    state.update(empty_state())
    state["device"] = device
    state["vehicle_profile"] = vehicle_profile_for_device(device)


def finish_pending(bridge: ControlBridge, state: dict, result: dict) -> None:
    with bridge.lock:
        pending = bridge.pending
        bridge.pending = None
    if pending is None:
        return
    pending["result"] = result
    state["command_result"] = result
    pending["event"].set()


def dispatch_request(fd: int, sequence: int, request: dict) -> tuple[int, int]:
    action = request["action"]
    params = request["params"]
    if action == "arm":
        command, values = 400, [1.0]
    elif action == "disarm":
        command, values = 400, [0.0]
    elif action == "set_mode":
        modes = {"STABILIZE": 0, "ALT_HOLD": 2, "GUIDED": 4, "LAND": 9, "GUIDED_NOGPS": 20}
        mode = str(params.get("mode", "")).upper()
        if mode not in modes:
            raise ValueError("不允许的飞行模式")
        command, values = 176, [1.0, float(modes[mode])]
    else:  # takeoff
        altitude = max(0.5, min(5.0, float(params.get("altitude", 1.0))))
        command, values = 22, [0.0, 0.0, 0.0, float("nan"), 0.0, 0.0, altitude]
    return send_command_long(fd, sequence, command, values), command


def main() -> int:
    args = parse_args()
    output = Path(args.output)
    state = empty_state()
    write_state(output, state)
    parser = MavlinkParser()
    serial_fd = None
    active_connection = None
    connection_opened_at = 0.0
    last_heartbeat = 0.0
    last_write = 0.0
    last_stream_request = 0.0
    last_gcs_heartbeat = 0.0
    tx_sequence = 0
    announced = False
    control = ControlBridge(state)
    control_server = start_control_server(control, args.control_host, args.control_port)
    print(f"[INFO] Waiting for Pixhawk on {args.connection} @ {args.baud}")
    print(f"[INFO] Flight control API {args.control_host}:{args.control_port} enabled={control.enabled} takeoff={control.takeoff_enabled}")

    try:
        while True:
            if serial_fd is None:
                try:
                    active_connection = resolve_serial_path(args.connection)
                    serial_fd = open_serial(active_connection, args.baud)
                    parser = MavlinkParser()
                    reset_vehicle_state(state, active_connection)
                    last_heartbeat = 0.0
                    last_stream_request = 0.0
                    connection_opened_at = time.monotonic()
                    announced = False
                    print(f"[OK] Opened {active_connection}")
                except (OSError, RuntimeError) as error:
                    reset_vehicle_state(state)
                    state["updated"] = time.time()
                    write_state(output, state)
                    print(f"[WARN] Serial unavailable: {error}")
                    time.sleep(2)
                    continue

            now = time.monotonic()
            try:
                if not active_connection or not serial_path_matches_fd(active_connection, serial_fd):
                    print("[WARN] Serial device changed; reopening")
                    os.close(serial_fd)
                    serial_fd = None
                    active_connection = None
                    last_heartbeat = 0.0
                    announced = False
                    reset_vehicle_state(state)
                    continue
                readable, _, _ = select.select([serial_fd], [], [], 0.5)
                data = os.read(serial_fd, 4096) if readable else b""
                for message_id, payload, system_id, component_id in parser.feed(data):
                    heartbeat = update_from_message(state, message_id, payload)
                    if message_id == 77 and len(payload) >= 3:  # COMMAND_ACK
                        command = struct.unpack_from("<H", payload, 0)[0]
                        result_code = payload[2]
                        with control.lock:
                            pending_request = control.pending
                            expected = None if pending_request is None else pending_request.get("command")
                            pending_action = None if pending_request is None else pending_request.get("action")
                        if expected == command and result_code != 5:
                            result_name = MAV_RESULT_NAMES.get(result_code, f"result_{result_code}")
                            finish_pending(control, state, {
                                "ok": result_code == 0,
                                "action": pending_action,
                                "result": result_name,
                                "error": None if result_code == 0 else f"{pending_action} command {result_name}",
                                "message": state.get("flight_message"),
                            })
                    if heartbeat:
                        last_heartbeat = time.monotonic()
                        if last_heartbeat - last_stream_request >= 5:
                            request_all_streams(serial_fd, tx_sequence)
                            tx_sequence = (tx_sequence + 1) & 0xFF
                            last_stream_request = last_heartbeat
                        if not announced:
                            print(f"[OK] MAVLink heartbeat system={system_id} component={component_id}")
                            print("[OK] Requested telemetry streams at 4 Hz (non-actuating)")
                            announced = True

                if not last_heartbeat and time.monotonic() - connection_opened_at > 8:
                    raise OSError("serial port opened but no MAVLink heartbeat received")

                now = time.monotonic()
                with control.lock:
                    pending = control.pending
                if pending is not None and now > pending["deadline"]:
                    finish_pending(control, state, {"ok": False, "action": pending["action"], "error": "飞控未返回COMMAND_ACK", "message": state.get("flight_message")})
                elif pending is None:
                    try:
                        request = control.commands.get_nowait()
                    except queue.Empty:
                        request = None
                    if request is not None:
                        try:
                            tx_sequence, command = dispatch_request(serial_fd, tx_sequence, request)
                            request["command"] = command
                            request["deadline"] = now + 3.0
                            with control.lock:
                                control.pending = request
                            print(f"[CONTROL] Sent {request['action']} MAV_CMD={command}")
                        except (OSError, ValueError) as error:
                            request["result"] = {"ok": False, "action": request["action"], "error": str(error)}
                            request["event"].set()
                if now - control.last_control_heartbeat < 3 and now - last_gcs_heartbeat >= 1:
                    tx_sequence = send_gcs_heartbeat(serial_fd, tx_sequence)
                    last_gcs_heartbeat = now
            except OSError as error:
                print(f"[WARN] Serial disconnected: {error}")
                os.close(serial_fd)
                serial_fd = None
                active_connection = None
                announced = False
                reset_vehicle_state(state)
                finish_pending(control, state, {"ok": False, "error": "串口断开"})
                continue

            now = time.monotonic()
            state["connected"] = now - last_heartbeat < 3
            if now - last_write >= 0.2:
                state["updated"] = time.time()
                write_state(output, state)
                last_write = now
    except KeyboardInterrupt:
        return 0
    finally:
        control_server.shutdown()
        if serial_fd is not None:
            os.close(serial_fd)
        state["connected"] = False
        state["updated"] = time.time()
        write_state(output, state)


if __name__ == "__main__":
    raise SystemExit(main())
