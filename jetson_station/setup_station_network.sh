#!/usr/bin/env bash
set -euo pipefail

CAMERA_IF="eth0"
MESH_IF="eth1"
CAMERA_LOCAL="192.168.1.2/32"
CAMERA_IP="192.168.1.50"
MESH_LOCAL="192.168.1.202/24"

if [[ ${EUID} -ne 0 ]]; then
  echo "请使用 sudo 运行此脚本。" >&2
  exit 1
fi

for dev in "${CAMERA_IF}" "${MESH_IF}"; do
  if [[ ! -e "/sys/class/net/${dev}" ]]; then
    echo "未找到网卡 ${dev}，停止配置。" >&2
    exit 1
  fi
done

camera_connection="$(nmcli -g GENERAL.CONNECTION device show "${CAMERA_IF}")"
mesh_connection="$(nmcli -g GENERAL.CONNECTION device show "${MESH_IF}")"

if [[ -z "${camera_connection}" || "${camera_connection}" == "--" ]]; then
  camera_connection="station-camera"
  nmcli connection add type ethernet ifname "${CAMERA_IF}" con-name "${camera_connection}"
fi

if [[ -z "${mesh_connection}" || "${mesh_connection}" == "--" ]]; then
  mesh_connection="station-mesh"
  nmcli connection add type ethernet ifname "${MESH_IF}" con-name "${mesh_connection}"
fi

nmcli connection modify "${camera_connection}" \
  connection.interface-name "${CAMERA_IF}" \
  connection.autoconnect yes \
  ipv4.method manual \
  ipv4.addresses "${CAMERA_LOCAL}" \
  ipv4.gateway "" \
  ipv4.dns "" \
  ipv4.never-default yes \
  ipv4.routes "${CAMERA_IP}/32" \
  ipv6.method disabled

nmcli connection modify "${mesh_connection}" \
  connection.interface-name "${MESH_IF}" \
  connection.autoconnect yes \
  ipv4.method manual \
  ipv4.addresses "${MESH_LOCAL}" \
  ipv4.gateway "" \
  ipv4.dns "" \
  ipv4.never-default yes \
  ipv4.routes "" \
  ipv6.method disabled

nmcli connection up "${mesh_connection}"
nmcli connection up "${camera_connection}"

echo
echo "网络配置完成："
ip -br -4 address show "${CAMERA_IF}"
ip -br -4 address show "${MESH_IF}"
ip -4 route show | grep -E '192\.168\.1\.(0/24|50)' || true

echo
if ping -c 2 -W 1 "${CAMERA_IP}" >/dev/null 2>&1; then
  echo "摄像头 ${CAMERA_IP}：连接正常"
else
  echo "摄像头 ${CAMERA_IP}：暂未响应，请检查摄像头供电和 eth0 网线"
fi

if ping -c 2 -W 1 192.168.1.100 >/dev/null 2>&1; then
  echo "LQ-3 地面节点 192.168.1.100：连接正常"
else
  echo "LQ-3 地面节点 192.168.1.100：暂未响应，请检查 eth1 网线和Mesh状态"
fi
