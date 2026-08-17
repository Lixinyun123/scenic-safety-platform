#!/usr/bin/env bash
set -euo pipefail

if [[ ${EUID} -ne 0 ]]; then
  echo "请使用 sudo 运行此脚本。" >&2
  exit 1
fi

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
archive="${script_dir}/mediamtx_v1.18.2_linux_arm64.tar.gz"
config="${script_dir}/mediamtx-station.yml"
install_dir="/opt/station-video"
service_file="/etc/systemd/system/station-video.service"
environment_file="/etc/station-video.env"

for required in "${archive}" "${config}"; do
  if [[ ! -f "${required}" ]]; then
    echo "缺少文件：${required}" >&2
    exit 1
  fi
done

expected="c78aa7a1bdab94b2b02be364661f17802143215dba37e1fa67c3e0849248b485"
actual="$(sha256sum "${archive}" | awk '{print $1}')"
if [[ "${actual}" != "${expected}" ]]; then
  echo "安装包校验失败，停止安装。" >&2
  exit 1
fi

if ! ping -c 1 -W 2 192.168.1.50 >/dev/null 2>&1; then
  echo "摄像头 192.168.1.50 当前不可达，请检查供电和 eth0 网线。" >&2
  exit 1
fi

read -r -p "摄像头用户名 [admin]: " camera_user
camera_user="${camera_user:-admin}"
read -r -s -p "摄像头密码: " camera_password
echo
if [[ -z "${camera_password}" ]]; then
  echo "摄像头密码不能为空。" >&2
  exit 1
fi

encoded_user="$(CAMERA_VALUE="${camera_user}" python3 -c 'import os, urllib.parse; print(urllib.parse.quote(os.environ["CAMERA_VALUE"], safe=""))')"
encoded_password="$(CAMERA_VALUE="${camera_password}" python3 -c 'import os, urllib.parse; print(urllib.parse.quote(os.environ["CAMERA_VALUE"], safe=""))')"
unset camera_password

install -d -m 0755 "${install_dir}"
tar -xzf "${archive}" -C "${install_dir}" mediamtx
install -m 0644 "${config}" "${install_dir}/mediamtx.yml"
chown -R root:root "${install_dir}"
chmod 0755 "${install_dir}/mediamtx"

umask 077
printf 'MTX_PATHS_STATION_SOURCE=rtsp://%s:%s@192.168.1.50:554/Streaming/Channels/101\n' \
  "${encoded_user}" "${encoded_password}" > "${environment_file}"
chmod 0600 "${environment_file}"

cat > "${service_file}" <<'UNIT'
[Unit]
Description=Jetson base-station camera gateway
After=network-online.target NetworkManager-wait-online.service
Wants=network-online.target

[Service]
Type=simple
User=jetson
Group=jetson
WorkingDirectory=/opt/station-video
EnvironmentFile=/etc/station-video.env
ExecStart=/opt/station-video/mediamtx /opt/station-video/mediamtx.yml
Restart=always
RestartSec=3
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
UNIT

systemctl daemon-reload
systemctl enable --now station-video.service
sleep 2

if ! systemctl is-active --quiet station-video.service; then
  echo "视频服务启动失败：" >&2
  systemctl --no-pager --full status station-video.service >&2 || true
  exit 1
fi

echo
echo "基站视频服务安装完成。"
echo "云平台地址：http://192.168.1.202:8889/station"
echo "本地识别地址：rtsp://127.0.0.1:8554/station"
echo "服务状态：$(systemctl is-active station-video.service)"

