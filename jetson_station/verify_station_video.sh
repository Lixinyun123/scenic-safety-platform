#!/usr/bin/env bash
set -euo pipefail

probe_log="/tmp/station-video-probe.log"
path_status="/tmp/station-video-path.json"
path_status_after="/tmp/station-video-path-after.json"

timeout 20 gst-launch-1.0 -q \
  rtspsrc location=rtsp://127.0.0.1:8554/station protocols=tcp latency=100 \
  ! rtph264depay ! h264parse ! fakesink >"${probe_log}" 2>&1 &
probe_pid=$!
trap 'kill "${probe_pid}" 2>/dev/null || true; wait "${probe_pid}" 2>/dev/null || true' EXIT

sleep 6
curl -fsS --max-time 5 http://127.0.0.1:9997/v3/paths/get/station >"${path_status}"
sleep 5
curl -fsS --max-time 5 http://127.0.0.1:9997/v3/paths/get/station >"${path_status_after}"
python3 -c '
import json, sys
d = json.load(open(sys.argv[1], encoding="utf-8"))
d2 = json.load(open(sys.argv[2], encoding="utf-8"))
if not d.get("ready"):
    raise SystemExit("station路径尚未就绪")
tracks = d.get("tracks", [])
if "H264" not in tracks:
    raise SystemExit("未检测到H264视频轨道")
print("READY=true")
print("TRACKS=" + ",".join(tracks))
print("BYTES_RECEIVED=" + str(d.get("bytesReceived", 0)))
print("READERS=" + str(len(d.get("readers", []))))
byte_delta = max(0, d2.get("bytesReceived", 0) - d.get("bytesReceived", 0))
print("BITRATE_MBPS=" + format(byte_delta * 8 / 5 / 1_000_000, ".2f"))
' "${path_status}" "${path_status_after}"
