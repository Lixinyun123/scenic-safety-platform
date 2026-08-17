# 树莓派 5 + SJCAM SJ4000 人员检测第一版

这一版只做一件事：从 SJ4000 的 USB 实时画面中检测 `person`，连续多帧检测到后保存带检测框的图片和 JSONL 日志。

> 重要：通用 YOLO 模型只能说“画面中疑似有人”，不能判定这个人正在溺水。真正的“落水人员”分类需要后续用自己的水面数据集训练。

## 独立服务架构

网页不再由摄像头识别进程托管，各数据源互不依赖：

- `dashboard-server.service`：始终监听 `8080`，只负责网页、状态聚合和控制转发。
- `water-person-detector.service`：只负责摄像头 AI 识别，写入 `output/detection_status.json`。
- `mavlink-telemetry.service`：独立读取飞控，写入 `output/flight_telemetry.json`。
- 地面端：预留 `POST /api/ingest/ground`，写入 `output/ground_terminal.json`；以后可经 4G 安全隧道主动上报。

摄像头、识别程序、飞控或地面端任一路离线时，网页仍可打开，并只把对应数据源标记为离线。地面端接入前应在 `dashboard-server.env` 设置高强度随机 `GROUND_INGEST_TOKEN`，并通过 HTTPS/VPN 隧道访问，不能把明文 8080 直接暴露到公网。

安装独立网页服务：

```bash
sudo install -m 0644 dashboard-server.service /etc/systemd/system/
sudo install -m 0644 water-person-detector.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now dashboard-server.service
sudo systemctl restart water-person-detector.service
```

## 1. 硬件连接

1. 树莓派 5 使用正规 5V/5A USB-C 电源，先在桌面上调试。
2. 使用“能传数据”的 Micro-USB 线连接 SJ4000 与树莓派 USB 口。
3. SJ4000 开机，屏幕如果出现模式选择，选 `WEB CAM` / `PC Camera` / `网络摄像头`，不要选“存储/磁盘”。
4. 调试时不要将摄像头放在密闭防水壳里，USB 连续输出和充电会发热。

SJ4000 通过 USB 连接时，防水壳无法完整密封。后续上无人机必须重新设计防水、散热、线缆拉力保护和防震固定。

## 2. 安装 Raspberry Pi OS 与工具

建议使用 64 位 Raspberry Pi OS Bookworm，先连显示器调试。

```bash
sudo apt update
sudo apt full-upgrade -y
sudo apt install -y python3-venv python3-opencv python3-matplotlib v4l-utils
```

把整个 `raspberry_pi_vision` 文件夹复制到树莓派，进入目录后执行：

```bash
/usr/bin/python3.13 -m venv --system-site-packages .venv313
source .venv313/bin/activate
python -m pip install torch==2.12.1+cpu torchvision==0.27.1+cpu \
  --index-url https://download.pytorch.org/whl/cpu
python -m pip install ultralytics==8.4.116 --no-deps
python -m pip install ncnn==1.0.20260526 pnnx==20260526
```

## 3. 第一关：只测摄像头

```bash
source .venv313/bin/activate
python camera_probe.py
```

成功时会显示：

```text
[OK] 已读到 1280x720 画面
```

并生成 `output/camera_test.jpg`。先打开这张图，确认画面没有黑屏、花屏或严重延迟。

如果不成功：

```bash
v4l2-ctl --list-devices
ls -l /dev/video*
```

- 如果摄像头是 `/dev/video2`，使用 `python camera_probe.py --index 2`。
- 只看到 USB 磁盘而没有 `/dev/videoN`：重新连接并在 SJ4000 上选 Webcam 模式。
- 什么都看不到：优先换 USB 数据线，很多充电线没有数据芯线。
- 仍然不出现 `/dev/videoN`：该批次固件可能不以 Linux UVC 设备输出，需要换标准 UVC USB 摄像头或 CSI 摄像头。

## 4. 第二关：检测人

树莓派默认使用已经导出的 NCNN 加速模型：

```bash
python detect_person.py
```

- 镜头前出现人时画出检测框。
- 连续 5 帧检测到人后报警。
- 截图保存到 `output/person_*.jpg`。
- 事件保存到 `output/detections.jsonl`。
- 按 `q` 或 `Ctrl+C` 退出。

如果是 SSH 无显示器运行：

```bash
python detect_person.py --no-display
```

在电脑或手机浏览器查看实时识别画面：

```bash
python detect_person.py --no-display --web
```

然后打开 `http://树莓派IP:8080`。网页会显示摄像头画面、人员框、FPS 和连续确认状态。

只跑 60 帧做性能测试：

```bash
python detect_person.py --no-display --max-frames 60
```

## 5. 树莓派上加速

如果是在一台新树莓派上重新安装，先用 `.pt` 模型验证功能，再导出 NCNN：

```bash
yolo export model=yolo26n.pt format=ncnn imgsz=384,640
mv yolo26n_ncnn_model yolo26n_640x384_ncnn_model
python detect_person.py
```

相机画面是 16:9。640x384 矩形模型仍将 1280x720 画面缩放为 640x360，因此人物像素大小与 640x640 方形模型相同，但省去了大量上下空白区域的计算。当前实测约为 20 FPS。

程序使用直接 NCNN 人员推理与四线程调度，不再经过通用 PyTorch/Ultralytics 预测流水线。

## 6. 开机自启动与日常管理

安装并立即启动服务：

```bash
sudo install -m 0644 water-detector-performance.service /etc/systemd/system/
sudo install -m 0644 water-person-detector.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now water-detector-performance.service
sudo systemctl enable --now water-person-detector.service
```

常用管理命令：

```bash
# 查看当前状态
sudo systemctl status water-person-detector.service

# 停止识别
sudo systemctl stop water-person-detector.service

# 启动识别
sudo systemctl start water-person-detector.service

# 修改程序后重新启动
sudo systemctl restart water-person-detector.service

# 实时查看运行日志，按 Ctrl+C 退出日志页面
journalctl -u water-person-detector.service -f

# 取消开机启动并立即停止
sudo systemctl disable --now water-person-detector.service
```

服务正常运行时，浏览器打开 `http://树莓派IP:8080`。

## 7. 运行逻辑测试

这项测试不需要摄像头和 YOLO：

```bash
python -m unittest discover -s tests -v
```

## 8. 第一轮验收标准

1. SJ4000 稳定出现为 `/dev/videoN`。
2. 默认以 MJPEG、1280x720、30fps 采集，YOLO 使用 640x384 矩形推理。
3. 连续运行 30 分钟不黑屏、不断连。
4. 3、5、10 米距离的真人和假人都分别测试。
5. 在水边只拍水面、漂浮物、船只等负样本，记录误检。
6. 不用真人做无人机投放测试。
