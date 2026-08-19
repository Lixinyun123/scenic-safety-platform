#!/usr/bin/env bash
set -Eeuo pipefail

REPOSITORY_URL="https://github.com/Lixinyun123/scenic-safety-platform.git"
APP_DIR="/opt/scenic-safety-platform"
STATE_DIR="/var/lib/scenic-safety-platform"
CONFIG_DIR="/etc/scenic-safety-platform"
SERVICE_NAME="scenic-platform"

if [[ "${EUID}" -ne 0 ]]; then
  echo "请使用 sudo 运行该脚本。" >&2
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends ca-certificates git nginx openssl python3

id -u scenic >/dev/null 2>&1 || useradd --system --home-dir /nonexistent --shell /usr/sbin/nologin scenic
install -d -o scenic -g scenic -m 0750 "$STATE_DIR"
install -d -o root -g scenic -m 0750 "$CONFIG_DIR"

if [[ -d "$APP_DIR/.git" ]]; then
  git -C "$APP_DIR" fetch --depth=1 origin master
  git -C "$APP_DIR" reset --hard origin/master
else
  rm -rf "$APP_DIR"
  git clone --depth=1 "$REPOSITORY_URL" "$APP_DIR"
fi

test -f "$APP_DIR/ground_station/base_station_server.py"
test -f "$APP_DIR/cloud_server/scenic-platform.service"
test -f "$APP_DIR/cloud_server/nginx-scenic-platform.conf"

ENV_FILE="$CONFIG_DIR/platform.env"
if [[ ! -f "$ENV_FILE" ]]; then
  umask 077
  cat > "$ENV_FILE" <<EOF
# Generated during first installation. Keep this file private.
BASE_INGEST_TOKEN=$(openssl rand -hex 32)
BASE_OPERATOR_TOKEN=$(openssl rand -hex 32)
# Video and flight-control paths remain disabled until a trusted gateway is configured.
ALLOW_FLIGHT_PROXY=false
DRONE_DASHBOARD_URL=http://127.0.0.1:18080
STATION_VIDEO_URL=
DRONE_VIDEO_URL=
EOF
  chown root:scenic "$ENV_FILE"
  chmod 0640 "$ENV_FILE"
fi

install -m 0644 "$APP_DIR/cloud_server/scenic-platform.service" "/etc/systemd/system/${SERVICE_NAME}.service"
install -m 0644 "$APP_DIR/cloud_server/nginx-scenic-platform.conf" /etc/nginx/sites-available/scenic-platform
rm -f /etc/nginx/sites-enabled/default
ln -sfn /etc/nginx/sites-available/scenic-platform /etc/nginx/sites-enabled/scenic-platform

nginx -t
systemctl daemon-reload
systemctl enable --now "$SERVICE_NAME"
systemctl reload nginx

echo
echo "部署完成。请访问：http://$(hostname -I | awk '{print $1}')/"
echo "公网访问请使用阿里云控制台显示的公网 IP。"
