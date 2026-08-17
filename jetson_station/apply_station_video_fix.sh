#!/usr/bin/env bash
set -euo pipefail

if [[ ${EUID} -ne 0 ]]; then
  echo "请使用 sudo 运行此脚本。" >&2
  exit 1
fi

fixed_config="/home/jetson/test-mediamtx.yml"
installed_config="/opt/station-video/mediamtx.yml"

if [[ ! -f "${fixed_config}" ]]; then
  echo "缺少修正配置：${fixed_config}" >&2
  exit 1
fi

install -o root -g root -m 0644 "${fixed_config}" "${installed_config}"
systemctl reset-failed station-video.service || true
systemctl restart station-video.service
sleep 3

if ! systemctl is-active --quiet station-video.service; then
  systemctl --no-pager --full status station-video.service >&2 || true
  journalctl -u station-video.service -n 40 --no-pager >&2 || true
  exit 1
fi

if ! curl -fsS --max-time 5 http://127.0.0.1:8889/station >/dev/null; then
  echo "WebRTC页面没有响应。" >&2
  exit 1
fi

echo "正在读取摄像头视频进行自检……"
probe_log="/tmp/station-video-probe.log"
path_status="/tmp/station-video-path.json"
timeout 20 runuser -u jetson -- gst-launch-1.0 -q \
  rtspsrc location=rtsp://127.0.0.1:8554/station protocols=tcp latency=100 \
  ! rtph264depay ! h264parse ! fakesink >"${probe_log}" 2>&1 &
probe_pid=$!
sleep 6

if ! curl -fsS --max-time 5 http://127.0.0.1:9997/v3/paths/get/station >"${path_status}"; then
  kill "${probe_pid}" 2>/dev/null || true
  wait "${probe_pid}" 2>/dev/null || true
  echo "无法读取视频路径状态。" >&2
  exit 1
fi

if ! python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); assert d.get("ready") is True; assert "H264" in d.get("tracks", [])' "${path_status}"; then
  kill "${probe_pid}" 2>/dev/null || true
  wait "${probe_pid}" 2>/dev/null || true
  echo "视频路径未就绪或未检测到H264画面。" >&2
  cat "${path_status}" >&2
  exit 1
fi

kill "${probe_pid}" 2>/dev/null || true
wait "${probe_pid}" 2>/dev/null || true

echo
echo "基站摄像头视频服务修复完成。"
echo "服务状态：$(systemctl is-active station-video.service)"
echo "云平台视频：http://192.168.1.202:8889/station"
echo "本地识别流：rtsp://127.0.0.1:8554/station"
