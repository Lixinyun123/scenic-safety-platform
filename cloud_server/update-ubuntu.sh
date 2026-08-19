#!/usr/bin/env bash
set -Eeuo pipefail

APP_DIR="/opt/scenic-safety-platform"
if [[ "${EUID}" -ne 0 ]]; then
  echo "请使用 sudo 运行该脚本。" >&2
  exit 1
fi

git -C "$APP_DIR" fetch --depth=1 origin master
git -C "$APP_DIR" reset --hard origin/master
install -m 0644 "$APP_DIR/cloud_server/scenic-platform.service" /etc/systemd/system/scenic-platform.service
install -m 0644 "$APP_DIR/cloud_server/nginx-scenic-platform.conf" /etc/nginx/sites-available/scenic-platform
nginx -t
systemctl daemon-reload
systemctl restart scenic-platform
systemctl reload nginx
echo "已更新至：$(git -C "$APP_DIR" rev-parse --short HEAD)"
