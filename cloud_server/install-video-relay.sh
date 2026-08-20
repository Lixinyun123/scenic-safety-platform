#!/usr/bin/env bash
set -Eeuo pipefail

VERSION="1.20.0"
PUBLIC_HOST=""
APP_ENV="/etc/scenic-safety-platform/platform.env"
VIDEO_ETC="/etc/scenic-video"
VIDEO_OPT="/opt/scenic-video"

usage() {
  echo "用法: sudo bash install-video-relay.sh --public-host <服务器公网IP或域名>" >&2
  exit 2
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --public-host) PUBLIC_HOST="${2:-}"; shift 2 ;;
    *) usage ;;
  esac
done

[[ "${EUID}" -eq 0 ]] || { echo "请使用 sudo 运行。" >&2; exit 1; }
[[ -n "$PUBLIC_HOST" ]] || usage
[[ -f "$APP_ENV" ]] || { echo "请先安装网页平台。" >&2; exit 1; }

apt-get update
apt-get install -y --no-install-recommends ca-certificates curl tar

id -u mediamtx >/dev/null 2>&1 || useradd --system --home-dir /nonexistent --shell /usr/sbin/nologin mediamtx
install -d -o root -g mediamtx -m 0750 "$VIDEO_ETC"
install -d -o root -g root -m 0755 "$VIDEO_OPT"

ARCHIVE="mediamtx_v${VERSION}_linux_amd64.tar.gz"
BASE_URL="https://github.com/bluenviron/mediamtx/releases/download/v${VERSION}"
TEMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TEMP_DIR"' EXIT
curl -fsSL "$BASE_URL/$ARCHIVE" -o "$TEMP_DIR/$ARCHIVE"
curl -fsSL "$BASE_URL/checksums.sha256" -o "$TEMP_DIR/checksums.sha256"
(cd "$TEMP_DIR" && grep " $ARCHIVE$" checksums.sha256 | sha256sum -c -)
tar -xzf "$TEMP_DIR/$ARCHIVE" -C "$TEMP_DIR"
install -m 0755 "$TEMP_DIR/mediamtx" "$VIDEO_OPT/mediamtx"

PUBLISH_FILE="$VIDEO_ETC/publish.env"
if [[ ! -f "$PUBLISH_FILE" ]]; then
  umask 077
  cat > "$PUBLISH_FILE" <<EOF
# Keep this file on the server. It is only used by the trusted Windows gateway.
VIDEO_PUBLISH_USER=relay
VIDEO_PUBLISH_PASSWORD=$(openssl rand -hex 32)
EOF
  chown root:mediamtx "$PUBLISH_FILE"
  chmod 0640 "$PUBLISH_FILE"
fi

# shellcheck disable=SC1090
source "$PUBLISH_FILE"
cat > "$VIDEO_ETC/mediamtx.yml" <<EOF
logLevel: info
logDestinations: [stdout]

api: true
apiAddress: 127.0.0.1:9997

rtsp: false
rtmp: true
rtmpAddress: :1935
hls: false
srt: false
playback: false

webrtc: true
webrtcAddress: :8889
webrtcAllowOrigins: ["http://${PUBLIC_HOST}", "https://${PUBLIC_HOST}"]
webrtcLocalUDPAddress: :8189
webrtcLocalTCPAddress: :8189
webrtcIPsFromInterfaces: false
webrtcAdditionalHosts: ["${PUBLIC_HOST}"]

authInternalUsers:
  - user: any
    pass:
    ips: []
    permissions:
      - action: read
        path: ""
  - user: ${VIDEO_PUBLISH_USER}
    pass: ${VIDEO_PUBLISH_PASSWORD}
    ips: []
    permissions:
      - action: publish
        path: station
      - action: publish
        path: drone

paths:
  station:
    source: publisher
  drone:
    source: publisher
EOF
chown root:mediamtx "$VIDEO_ETC/mediamtx.yml"
chmod 0640 "$VIDEO_ETC/mediamtx.yml"

replace_env() {
  local key="$1" value="$2"
  if grep -q "^${key}=" "$APP_ENV"; then
    sed -i "s|^${key}=.*|${key}=${value}|" "$APP_ENV"
  else
    printf '%s=%s\n' "$key" "$value" >> "$APP_ENV"
  fi
}

replace_env STATION_VIDEO_URL "http://${PUBLIC_HOST}:8889/station?controls=false&muted=true&autoplay=true&playsInline=true"
replace_env DRONE_VIDEO_URL "http://${PUBLIC_HOST}:8889/drone?controls=false&muted=true&autoplay=true&playsInline=true"

install -m 0644 "$(dirname "$0")/mediamtx.service" /etc/systemd/system/mediamtx.service
systemctl daemon-reload
systemctl enable --now mediamtx
systemctl restart scenic-platform

echo
echo "视频汇聚服务已启动。"
echo "在阿里云轻量应用服务器防火墙放行：TCP 1935、TCP 8889、TCP/UDP 8189。"
echo "Windows 网关配置请在服务器本机查看：sudo cat $PUBLISH_FILE"
echo "两路推流地址格式：rtmp://${VIDEO_PUBLISH_USER}:<密码>@${PUBLIC_HOST}:1935/station 和 .../drone"
