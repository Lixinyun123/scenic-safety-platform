# 基站端第一阶段

基站端运行在地面电脑上，负责接收检测设备的状态与目标坐标，并由操作员确认后生成无人机任务。

当前已经实现：

- 检测设备心跳与位置上报；
- 一个上报中携带多个疑似目标坐标；
- 坐标和置信度校验；
- 人工确认目标；
- 为指定无人机准备任务；
- 状态原子持久化和 JSONL 事件日志；
- 设备上报与操作员接口使用不同令牌；
- 自动起飞及任务下发默认锁定。

## 本地运行

```powershell
$env:BASE_INGEST_TOKEN = "为检测设备生成的随机令牌"
$env:BASE_OPERATOR_TOKEN = "为操作台生成的另一个随机令牌"
python -m ground_station.base_station_server --host 127.0.0.1 --port 8090
```

状态接口：`GET http://127.0.0.1:8090/api/base/status`

检测设备上报示例：

```json
{
  "device_id": "GROUND-01",
  "name": "岸边检测设备01",
  "latitude": 30.100000,
  "longitude": 114.200000,
  "battery_percent": 88,
  "health": "normal",
  "targets": [
    {
      "latitude": 30.100100,
      "longitude": 114.200200,
      "confidence": 0.91
    }
  ]
}
```

后续阶段将接入现有网页、地图目标标记和无人机任务网关。任务下发必须校验飞机在线、自检通过、遥控器可接管及任务坐标合法，不能由检测结果直接触发起飞。
