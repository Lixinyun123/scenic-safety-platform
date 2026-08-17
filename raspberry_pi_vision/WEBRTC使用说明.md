# H.264 + WebRTC 使用说明

系统现在由两个开机服务组成：

- `mediamtx.service`：独占 SJ4000，将相机原生 1280×720、30 FPS H.264 分发给网页和识别程序。
- `water-person-detector.service`：读取本机 RTSP 共享流，以 NCNN 识别人，并把识别框坐标叠加到网页。

## 打开实时画面

- 当前局域网：`http://172.20.10.2:8080`
- Tailscale 私网：`http://100.94.255.54:8080`
- LQ-3 图传直连：`http://192.168.1.123:8080`

LQ-3 固定地址：树莓派移动端侧为 `192.168.1.123/24`，地面站电脑为
`192.168.1.128/24`。图传网卡不设置默认网关和 DNS，正常上网仍走 Wi-Fi。

网页显示“`H.264 WebRTC 低延迟模式`”表示正在局域网直连。

无需安装软件的公网地址：`https://raspberrypi.tailbcf74e.ts.net/`。公网自动使用
H.264 低延迟 HLS，任何拿到链接的人都能观看。

## 常用管理命令

```bash
# 查看两个服务
systemctl status mediamtx.service water-person-detector.service

# 查看实时日志，按 Ctrl+C 退出
journalctl -u mediamtx.service -u water-person-detector.service -f

# 停止识别与视频
sudo systemctl stop water-person-detector.service mediamtx.service

# 启动视频与识别
sudo systemctl start mediamtx.service water-person-detector.service

# 重新启动
sudo systemctl restart mediamtx.service water-person-detector.service

# 检查是否开机自启动
systemctl is-enabled mediamtx.service water-person-detector.service
```

配置文件：

- `/etc/mediamtx.yml`
- `/etc/systemd/system/mediamtx.service`
- `/etc/systemd/system/water-person-detector.service`
