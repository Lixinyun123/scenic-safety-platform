# Windows现场云端网关

本程序用于地面电脑同时连接LQ-3和互联网时，将Jetson与树莓派的两路H.264视频转推至公网媒体服务器。设备端不需要互联网。

## 网络要求

- LQ-3网卡可访问`192.168.1.0/24`，该网卡不要填写默认网关。
- WiFi、手机热点或4G负责默认互联网出口。
- Jetson默认流：`rtsp://192.168.1.202:8554/station`。
- 无人机默认流：`rtsp://192.168.1.123:8554/rescue`。

## 使用

1. 在Windows安装FFmpeg，并确保`ffmpeg -version`可运行。
2. 首次运行`start_cloud_gateway.ps1 -Check`生成`cloud-gateway.env`。
3. 填写服务器提供的两个推流地址。
4. 再运行`start_cloud_gateway.ps1`。

程序使用视频原码转推，不重新编码，CPU占用较低；源断线或公网中断后会自动重连。运行状态写入`gateway-status.json`。

只有在公网媒体服务器部署完成后，才能获得真实推流地址。不要把包含发布令牌的`cloud-gateway.env`提交到公开GitHub仓库。
