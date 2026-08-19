# 阿里云公网部署包

本目录用于把“景区安全智能监测平台”部署到 Ubuntu 22.04 服务器。它采用
Python 标准库后台 + Nginx，适合 2 核 2 GiB 的轻量应用服务器；不需要 Docker，
也不会在服务器上运行模型识别。

## 首次部署

1. 将完整项目推送到 GitHub 的 `master` 分支。
2. 在阿里云“远程连接”终端中，以有 `sudo` 权限的用户执行：

```bash
git clone --depth=1 https://github.com/Lixinyun123/scenic-safety-platform.git ~/scenic-deploy
sudo bash ~/scenic-deploy/cloud_server/install-ubuntu.sh
```

3. 在轻量应用服务器防火墙中确认 TCP `80` 已放行（默认通常已放行）。
4. 用浏览器访问 `http://服务器公网IP/`。正式对外使用时应绑定域名、完成备案（如适用）并启用 HTTPS。

安装脚本会在 `/etc/scenic-safety-platform/platform.env` 创建两条随机令牌：

- `BASE_INGEST_TOKEN`：仅给 STM32 / Jetson / 网关的设备上报使用。
- `BASE_OPERATOR_TOKEN`：综合指挥页面执行“确认事件 / 派遣任务”时使用。

它们只保存在服务器上，禁止提交到 GitHub、浏览器运行时配置或聊天消息中。

## 运行状态

```bash
sudo systemctl status scenic-platform
sudo journalctl -u scenic-platform -n 100 --no-pager
curl http://127.0.0.1:8090/api/base/status
```

## 后续接入视频和无人机

安装的默认配置**不会**转发飞控命令，`ALLOW_FLIGHT_PROXY=false`。这意味着公开的
平台先只提供页面、基站数据和告警；待 Windows 网关或路由器直连网关建立了受认证的
加密回传后，才在服务器上单独开启视频和控制桥。这样不会因为部署网站而把飞控控制
端口暴露到公网。

两种后续视频接入方式都会接到同一个服务器接口：

1. LQ-3 → Windows 网关 → 服务器；
2. LQ-3 → 可联网路由器 → 服务器。

## 更新

推送新代码到 GitHub 后，在服务器执行：

```bash
sudo /opt/scenic-safety-platform/cloud_server/update-ubuntu.sh
```
