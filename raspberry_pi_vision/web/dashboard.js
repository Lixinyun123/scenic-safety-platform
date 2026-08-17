(() => {
  "use strict";
  const $ = (s) => document.querySelector(s);
  const canvas = $("#overlay");
  const ctx = canvas.getContext("2d");
  const rtc = $("#rtc");
  const funnel = location.hostname.endsWith(".ts.net");
  let lastConfirmed = false;
  let toastTimer;
  let map;
  let aircraftMarker;
  let flightPath;
  let mapCentered = false;
  let latestTelemetry;
  let latestDetection;
  let latestSources = { air_unit:{connected:false}, flight:{connected:false}, video:{connected:false}, vision:{connected:false}, ground:{connected:false} };
  let lastAirUnitSeen = 0;
  let controlPin = "";
  let controlAvailable = false;
  let takeoffEnabled = false;
  let sharedMissionActive = false;
  const pathPoints = [];
  let currentLanguage = "zh-CN";
  try { currentLanguage = localStorage.getItem("dashboardLanguage") || "zh-CN"; } catch (_) {}

  const STATIC_EN = {
    "澜盾搜救": "AquaShield Rescue", "实时态势": "Live Operations", "目标事件": "Target Events",
    "设备管理": "Device Management", "数据管理": "Data Management", "算法管理": "Algorithm Management",
    "卫星地图加载中": "Loading satellite map", "无互联网时仍可使用视频与遥测功能": "Video and telemetry remain available offline",
    "飞行器": "Aircraft", "水域搜救无人机": "Water Rescue UAV", "待命": "Standby", "综合状态": "Overall Status",
    "飞行状态": "Flight Status", "GPS定位": "GPS Fix", "飞行模式": "Flight Mode", "解锁状态": "Arm Status",
    "气压计高度": "Baro Altitude", "光流高度": "Optical-flow AGL", "水平速度": "Ground Speed", "飞行电池": "Flight Battery", "识别FPS": "AI FPS",
    "当前目标": "Targets", "链路ms": "Link ms", "卫星数": "Satellites", "机载识别画面": "Onboard Vision",
    "AI识别": "AI Detection", "视频链路": "Video Link", "确认目标": "Confirm Target", "自动化": "Automation",
    "只读阶段": "Read-only", "执行任务": "Tasks", "循环次数": "Cycles", "任务成功率": "Success Rate",
    "目标识别": "Target Detection", "查看详情 ›": "View Details ›", "AI目标状态": "AI Target Status",
    "最高置信度": "Top Confidence", "识别服务已连接": "Detection Service Connected", "等待画面目标": "Waiting for a target",
    "实时": "Live", "Pixhawk等待接入": "Waiting for Pixhawk", "控制功能保持锁定": "Controls remain locked",
    "待处理": "Pending", "确认目标位置": "Confirm Target Position", "飞行数据": "Flight Data",
    "飞行架次": "Flights", "飞行时长": "Flight Time", "飞行里程": "Distance",
    "飞行控制": "Flight Control", "安全锁定": "Safety Locked", "起飞准备": "Takeoff Readiness",
    "等待自检": "Awaiting Check", "连接飞控后检查系统状态": "Connect the FC to check system status",
    "检查通过": "Checks Passed", "飞控链路": "FC Link", "电池状态": "Battery",
    "定位状态": "Positioning", "光流测距": "Optical Range", "光流状态": "Optical Flow", "下视测距": "Downward Range", "等待数据": "Waiting",
    "执行自检": "Run Check", "解锁": "Arm", "起飞": "Takeoff", "遥控器优先": "RC Priority",
    "网页飞控指令尚未启用": "Web flight commands are not enabled", "目标态势": "Target Awareness",
    "台架模式 · 起飞锁定": "Bench mode · Takeoff locked",
    "AI 在线": "AI Online", "任务摘要": "Mission Summary", "本次飞行": "Current Flight", "发现目标": "Targets Found"
  };
  const TEXT = {
    "zh-CN": {
      fc_waiting:"等待飞控", fc_online:"飞控在线", live_position:"实时定位", online:"在线", offline:"未连接",
      gps_waiting:"等待定位", positioned:"已定位", armed:"已解锁", disarmed:"已锁定", gps_coordinates:"等待GPS定位",
      aircraft_online:"机载端在线", aircraft_connecting:"机载端连接中", ai_running:"AI实时运行", ai_connecting:"AI连接中",
      suspected_person:"疑似人员", targets:"目标", person_found:"发现疑似落水人员", monitoring:"持续监测中",
      target_confirmed:"目标已确认", validating:"识别校验中", scanning:"扫描中", evidence_saved:"证据已保存，等待人工核实",
      just_now:"刚刚", coming_later:"将在后续阶段接入", fullscreen_denied:"当前浏览器未允许全屏",
      gps_required:"接入GPS后才能确认目标位置"
      ,checks_ready:"项通过，可以继续地面检查", checks_blocked:"项通过，尚未满足起飞条件",
      check_complete:"基础自检完成", fc_normal:"链路正常", battery_normal:"电量充足", battery_low:"电量不足",
      gps_normal:"定位正常", gps_missing:"等待GPS", flow_normal:"光流正常", flow_missing:"等待光流", range_normal:"测距正常", range_missing:"等待测距",
      safety_note:"实际解锁前仍需飞控预解锁检查"
      ,bench_control:"台架控制", disarm:"上锁", enter_pin:"请输入6位控制PIN", command_ok:"飞控已确认指令",
      command_failed:"飞控拒绝指令", takeoff_locked:"台架模式禁止起飞"
    },
    en: {
      fc_waiting:"Waiting for FC", fc_online:"Flight Controller Online", live_position:"Live Position", online:"Online", offline:"Offline",
      gps_waiting:"Waiting for Fix", positioned:"Positioned", armed:"Armed", disarmed:"Disarmed", gps_coordinates:"Waiting for GPS",
      aircraft_online:"Air Unit Online", aircraft_connecting:"Connecting to Air Unit", ai_running:"AI Running", ai_connecting:"Connecting AI",
      suspected_person:"Possible Person", targets:"targets", person_found:"Possible Person in Water", monitoring:"Monitoring",
      target_confirmed:"Target Confirmed", validating:"Validating", scanning:"Scanning", evidence_saved:"Evidence saved; awaiting review",
      just_now:"Just now", coming_later:" will be available in a later phase", fullscreen_denied:"Fullscreen is not available",
      gps_required:"GPS is required to confirm the target position"
      ,checks_ready:" checks passed; continue ground inspection", checks_blocked:" checks passed; not ready for takeoff",
      check_complete:"Basic check complete", fc_normal:"Link healthy", battery_normal:"Battery ready", battery_low:"Battery low",
      gps_normal:"Position ready", gps_missing:"Waiting for GPS", flow_normal:"Flow healthy", flow_missing:"Waiting for flow", range_normal:"Range healthy", range_missing:"Waiting for range",
      safety_note:"Flight-controller pre-arm checks are still required"
      ,bench_control:"Bench Control", disarm:"Disarm", enter_pin:"Enter the 6-digit control PIN", command_ok:"Command acknowledged",
      command_failed:"Command rejected", takeoff_locked:"Takeoff is locked in bench mode"
    }
  };
  const staticTextNodes = [];
  const tr = (key) => (TEXT[currentLanguage] || TEXT["zh-CN"])[key] || key;

  async function fetchWithTimeout(url, options = {}, timeout = 1200) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeout);
    try { return await fetch(url, { ...options, signal: controller.signal }); }
    finally { clearTimeout(timer); }
  }

  function captureStaticText() {
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    let node;
    while ((node = walker.nextNode())) {
      const key = node.nodeValue.trim();
      if (STATIC_EN[key]) staticTextNodes.push({ node, key });
    }
  }

  function applyLanguage(language, persist = true) {
    currentLanguage = language === "en" ? "en" : "zh-CN";
    document.documentElement.lang = currentLanguage;
    document.title = currentLanguage === "en" ? "AquaShield · Water Rescue Command" : "澜盾 · 水域搜救指挥平台";
    staticTextNodes.forEach(({ node, key }) => {
      node.nodeValue = node.nodeValue.replace(node.nodeValue.trim(), currentLanguage === "en" ? STATIC_EN[key] : key);
    });
    $("#languageLabel").textContent = currentLanguage === "en" ? "English" : "简体中文";
    document.querySelectorAll("[data-language]").forEach((button) => button.classList.toggle("active", button.dataset.language === currentLanguage));
    if (persist) { try { localStorage.setItem("dashboardLanguage", currentLanguage); } catch (_) {} }
    if (latestTelemetry) updateTelemetry(latestTelemetry);
    if (latestDetection) updateTarget(latestDetection);
  }

  let videoUrl = funnel
    ? `https://${location.hostname}:8443/rescue?controls=false&muted=true&autoplay=true&playsInline=true`
    : `http://${location.hostname}:8889/rescue?controls=false&muted=true&autoplay=true&playsInline=true`;
  let videoStarted = false;

  async function loadRuntimeConfig() {
    try {
      const response = await fetchWithTimeout("/api/config", { cache: "no-store" }, 1000);
      const config = await response.json();
      if (config.video_url) videoUrl = config.video_url;
    } catch (_) {}
  }

  function updateVideoSource(online) {
    if (online && !videoStarted) {
      rtc.src = videoUrl;
      videoStarted = true;
    }
    if (!online && videoStarted) {
      rtc.src = "about:blank";
      videoStarted = false;
    }
    $("#videoBody").classList.toggle("source-offline", !online);
    $("#videoPlaceholder").classList.toggle("hidden", online);
  }

  function formatLastSeen(timestamp) {
    if (!timestamp) return currentLanguage === "en" ? "Awaiting air unit" : "等待机载端";
    const seconds = Math.max(0, Math.round((Date.now() - timestamp) / 1000));
    if (seconds < 60) return currentLanguage === "en" ? `Last seen ${seconds}s ago` : `最后在线 ${seconds}秒前`;
    return currentLanguage === "en" ? `Last seen ${Math.floor(seconds / 60)}m ago` : `最后在线 ${Math.floor(seconds / 60)}分钟前`;
  }

  function applySourceState(sources) {
    latestSources = sources;
    const airUnitOnline = Boolean(sources.air_unit?.connected);
    const flightOnline = Boolean(sources.flight?.connected);
    const videoOnline = Boolean(airUnitOnline && sources.video?.connected);
    const visionOnline = Boolean(airUnitOnline && sources.vision?.connected);
    if (airUnitOnline) lastAirUnitSeen = Date.now();

    const aircraftPanel = $("#aircraftPanel");
    const flightControlPanel = $("#flightControlPanel");
    const targetAwarenessPanel = $("#targetAwarenessPanel");
    aircraftPanel.classList.toggle("device-offline", !flightOnline);
    aircraftPanel.classList.remove("device-degraded");
    flightControlPanel.classList.toggle("device-offline", !flightOnline);
    targetAwarenessPanel.classList.toggle("device-offline", !visionOnline);
    flightControlPanel.dataset.offlineLabel = !flightOnline ? (currentLanguage === "en" ? "FLIGHT CONTROLLER OFFLINE · CONTROLS LOCKED" : "飞控未连接 · 操作已锁定") : "";
    targetAwarenessPanel.dataset.offlineLabel = !visionOnline ? (currentLanguage === "en" ? "DETECTION SERVICE OFFLINE" : "识别服务未连接") : "";
    $("#videoConsole").classList.toggle("device-offline", !videoOnline);

    if (!airUnitOnline) {
      $("#aircraftOnline").textContent = currentLanguage === "en" ? "Device Offline" : "设备未连接";
      $("#deviceLastSeen").textContent = formatLastSeen(lastAirUnitSeen);
      $("#aircraftStateBadge").textContent = currentLanguage === "en" ? "Offline" : "离线";
      $("#aircraftStateBadge").className = "standby offline";
      $("#overallStatus").textContent = "--";
    } else if (!flightOnline) {
      $("#aircraftOnline").textContent = currentLanguage === "en" ? "Aircraft Offline" : "无人机未连接";
      $("#deviceLastSeen").textContent = currentLanguage === "en" ? "Air unit online · Waiting for FC" : "机载端在线 · 等待飞控";
      $("#aircraftStateBadge").textContent = currentLanguage === "en" ? "Offline" : "离线";
      $("#aircraftStateBadge").className = "standby offline";
      $("#overallStatus").textContent = "--";
    } else {
      $("#aircraftOnline").textContent = currentLanguage === "en" ? "Aircraft Online" : "无人机在线";
      $("#deviceLastSeen").textContent = currentLanguage === "en" ? "Live telemetry" : "遥测实时";
      $("#aircraftStateBadge").textContent = latestTelemetry?.armed ? tr("armed") : (currentLanguage === "en" ? "Standby" : "待命");
      $("#aircraftStateBadge").className = "standby online";
      $("#overallStatus").textContent = latestTelemetry?.armed ? "飞行" : "就绪";
    }

    $("#runPreflightCheck").disabled = !flightOnline;
    $("#visionEventTitle").textContent = visionOnline ? (currentLanguage === "en" ? "Detection service connected" : "识别服务已连接") : (currentLanguage === "en" ? "Detection service offline" : "识别服务未连接");
    $("#visionEventText").textContent = visionOnline ? (currentLanguage === "en" ? "Waiting for targets" : "等待画面目标") : (airUnitOnline ? (currentLanguage === "en" ? "Check the AI process" : "请检查AI识别程序") : (currentLanguage === "en" ? "Waiting for the aircraft" : "等待无人机设备接入"));
    $("#visionEventTime").textContent = visionOnline ? tr("online") : tr("offline");
    $("#visionConnectionEvent i").className = visionOnline ? "cyan" : "";

    if (!airUnitOnline) {
      $("#videoPlaceholderTitle").textContent = currentLanguage === "en" ? "Aircraft Offline" : "无人机设备未连接";
      $("#videoPlaceholderText").textContent = currentLanguage === "en" ? "Waiting for the air unit data link" : "等待机载端接入图传网络";
    } else if (!videoOnline) {
      $("#videoPlaceholderTitle").textContent = currentLanguage === "en" ? "Camera Video Offline" : "摄像头视频未连接";
      $("#videoPlaceholderText").textContent = currentLanguage === "en" ? "Check the camera and video service" : "请检查摄像头与视频服务";
    }
    updateVideoSource(videoOnline);
    if (aircraftMarker) aircraftMarker.setOpacity(flightOnline ? 1 : .28);
  }

  async function refreshSources() {
    try {
      const response = await fetchWithTimeout("/api/sources", { cache: "no-store" }, 1200);
      if (!response.ok) throw new Error(String(response.status));
      applySourceState(await response.json());
    } catch (_) {
      applySourceState({ air_unit:{connected:false}, flight:{connected:false}, video:{connected:false}, vision:{connected:false}, ground:{connected:false} });
    } finally {
      setTimeout(refreshSources, 1200);
    }
  }

  function initMap() {
    if (!window.L) return;
    map = L.map("map", { zoomControl: false, attributionControl: true, preferCanvas: true })
      .setView([30.5928, 114.3055], 7);
    L.tileLayer("https://webst0{s}.is.autonavi.com/appmaptile?style=6&x={x}&y={y}&z={z}", {
      subdomains: ["1", "2", "3", "4"],
      maxZoom: 18,
      attribution: "高德卫星地图"
    }).addTo(map);
    L.tileLayer("https://webst0{s}.is.autonavi.com/appmaptile?style=8&x={x}&y={y}&z={z}", {
      subdomains: ["1", "2", "3", "4"],
      maxZoom: 18,
      opacity: .95,
      attribution: "中文路网"
    }).addTo(map);
    flightPath = L.polyline([], { color: "#21b7ff", weight: 3, opacity: .82 }).addTo(map);
  }

  function outsideChina(lat, lon) {
    return lon < 72.004 || lon > 137.8347 || lat < .8293 || lat > 55.8271;
  }

  function transformLat(x, y) {
    let value = -100 + 2 * x + 3 * y + .2 * y * y + .1 * x * y + .2 * Math.sqrt(Math.abs(x));
    value += (20 * Math.sin(6 * x * Math.PI) + 20 * Math.sin(2 * x * Math.PI)) * 2 / 3;
    value += (20 * Math.sin(y * Math.PI) + 40 * Math.sin(y / 3 * Math.PI)) * 2 / 3;
    value += (160 * Math.sin(y / 12 * Math.PI) + 320 * Math.sin(y * Math.PI / 30)) * 2 / 3;
    return value;
  }

  function transformLon(x, y) {
    let value = 300 + x + 2 * y + .1 * x * x + .1 * x * y + .1 * Math.sqrt(Math.abs(x));
    value += (20 * Math.sin(6 * x * Math.PI) + 20 * Math.sin(2 * x * Math.PI)) * 2 / 3;
    value += (20 * Math.sin(x * Math.PI) + 40 * Math.sin(x / 3 * Math.PI)) * 2 / 3;
    value += (150 * Math.sin(x / 12 * Math.PI) + 300 * Math.sin(x / 30 * Math.PI)) * 2 / 3;
    return value;
  }

  function wgs84ToGcj02(lat, lon) {
    if (outsideChina(lat, lon)) return [lat, lon];
    const a = 6378245, ee = .00669342162296594323;
    let dLat = transformLat(lon - 105, lat - 35);
    let dLon = transformLon(lon - 105, lat - 35);
    const radLat = lat / 180 * Math.PI;
    let magic = Math.sin(radLat);
    magic = 1 - ee * magic * magic;
    const sqrtMagic = Math.sqrt(magic);
    dLat = dLat * 180 / ((a * (1 - ee)) / (magic * sqrtMagic) * Math.PI);
    dLon = dLon * 180 / (a / sqrtMagic * Math.cos(radLat) * Math.PI);
    return [lat + dLat, lon + dLon];
  }

  function updateTelemetry(t) {
    const latitude = Number(t.latitude);
    const longitude = Number(t.longitude);
    const fresh = Date.now() / 1000 - Number(t.updated || 0) < 3;
    const flightConnected = Boolean(t.connected && fresh);
    const located = Boolean(flightConnected && t.latitude != null && t.longitude != null && Number.isFinite(latitude) && Number.isFinite(longitude));
    const rangeFresh = t.height_agl != null && Date.now() / 1000 - Number(t.range_updated || 0) < 2;
    updatePreflight(t, { flightConnected, located, rangeFresh });
    $("#flightState").textContent = flightConnected ? tr("online") : tr("offline");
    $("#gpsState").textContent = located ? (t.gps_fix || tr("positioned")) : tr("gps_waiting");
    $("#flightMode").textContent = t.flight_mode || "--";
    $("#armedState").textContent = t.armed === true ? tr("armed") : t.armed === false ? tr("disarmed") : "--";
    $("#flightAltitude").textContent = t.relative_altitude == null ? "--" : Number(t.relative_altitude).toFixed(1);
    $("#flowAltitude").textContent = rangeFresh ? Number(t.height_agl).toFixed(2) : "--";
    $("#baroHeightMetric").title = currentLanguage === "en" ? "FC relative barometric altitude" : "飞控相对气压高度";
    $("#flowHeightMetric").title = rangeFresh
      ? `${currentLanguage === "en" ? "Downward rangefinder · Optical flow quality" : "下视测距 · 光流质量"}: ${t.optical_flow_quality ?? "--"}`
      : (currentLanguage === "en" ? "Waiting for downward range data" : "等待下视测距数据");
    $("#groundSpeed").textContent = t.ground_speed == null ? "--" : Number(t.ground_speed).toFixed(1);
    $("#batteryPercent").textContent = t.battery_percent == null ? "--%" : `${Math.round(t.battery_percent)}%`;
    $("#batteryBar").style.width = t.battery_percent == null ? "0" : `${Math.max(0, Math.min(100, t.battery_percent))}%`;
    $("#satelliteCount").textContent = t.satellites == null ? "--" : t.satellites;
    const compassHeading = t.heading == null ? 0 : Number(t.heading);
    $("#headingValue").textContent = t.heading == null ? "---°" : `${Math.round(compassHeading)}°`;
    const headingNames = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"];
    $("#headingCardinal").textContent = t.heading == null ? "--" : headingNames[Math.round(compassHeading / 45) % 8];
    $("#compassNeedle").style.transform = "translate(-50%,-50%)";
    $("#aslValue").textContent = t.relative_altitude == null ? "BARO: --" : `BARO: ${Number(t.relative_altitude).toFixed(1)}m`;
    $("#aglValue").textContent = rangeFresh ? `AGL: ${Number(t.height_agl).toFixed(2)}m` : "AGL: --";
    $("#speedValue").textContent = t.ground_speed == null ? "SPD: --" : `SPD: ${Number(t.ground_speed).toFixed(1)}m/s`;
    $("#coordinateStatus").textContent = located ? `${latitude.toFixed(6)}, ${longitude.toFixed(6)}` : tr("gps_coordinates");
    if (!map || !located) {
      if (aircraftMarker) aircraftMarker.setOpacity(.42);
      return;
    }
    const point = wgs84ToGcj02(latitude, longitude);
    if (!aircraftMarker) {
      const icon = L.divIcon({ className: "aircraft-map-icon", html: '<div class="aircraft-map-marker"><span>▲</span></div>', iconSize: [34, 34], iconAnchor: [17, 17] });
      aircraftMarker = L.marker(point, { icon, zIndexOffset: 1000 }).addTo(map).bindTooltip("RESCUE-01", { permanent: true, direction: "right", className: "aircraft-map-label", offset: [13, 0] });
    } else {
      aircraftMarker.setLatLng(point).setOpacity(1);
    }
    const markerElement = aircraftMarker.getElement();
    if (markerElement) markerElement.querySelector(".aircraft-map-marker").style.transform = `rotate(${Number(t.heading || 0)}deg)`;
    const last = pathPoints[pathPoints.length - 1];
    if (!last || Math.abs(last[0] - point[0]) > 1e-7 || Math.abs(last[1] - point[1]) > 1e-7) {
      pathPoints.push(point);
      if (pathPoints.length > 500) pathPoints.shift();
      flightPath.setLatLngs(pathPoints);
    }
    if (!mapCentered) {
      map.setView(point, 16);
      mapCentered = true;
    }
  }

  function setPreflightItem(id, passed, text) {
    const item = $(id);
    item.classList.toggle("pass", passed);
    item.classList.toggle("warn", !passed);
    $(`${id}Text`).textContent = text;
  }

  function updatePreflight(t, computed) {
    const flightConnected = computed?.flightConnected ?? false;
    const rangeFresh = computed?.rangeFresh ?? false;
    const controllerReady = flightConnected && [3, 4].includes(Number(t.system_status));
    const batteryReady = flightConnected && t.battery_percent != null && Number(t.battery_percent) >= 30;
    const gpsBaro = t.vehicle_profile === "gps_baro";
    const sensorHealth = t.sensor_health || {};
    const ekfFlags = Number(t.ekf_flags || 0);
    const ekfPositionReady = Boolean(ekfFlags & 16) && !Boolean(ekfFlags & 1024);
    const gpsReady = flightConnected && Number(t.gps_fix_type || 0) >= 3 && Number(t.satellites || 0) >= 6 && sensorHealth.gps === true;
    const navigationReady = gpsBaro
      ? gpsReady && ekfPositionReady
      : flightConnected && Number(t.optical_flow_quality || 0) >= 50;
    const altitudeReady = gpsBaro
      ? flightConnected && sensorHealth.barometer === true
      : flightConnected && rangeFresh;
    const checks = [controllerReady, batteryReady, navigationReady, altitudeReady];
    const passed = checks.filter(Boolean).length;
    $("#checkFlowLabel").textContent = gpsBaro ? (currentLanguage === "en" ? "GPS Position" : "GPS定位") : (currentLanguage === "en" ? "Optical Flow" : "光流状态");
    $("#checkRangeLabel").textContent = gpsBaro ? (currentLanguage === "en" ? "Barometer" : "气压计") : (currentLanguage === "en" ? "Downward Range" : "下视测距");
    setPreflightItem("#checkFlightController", controllerReady, controllerReady ? tr("fc_normal") : (flightConnected ? (currentLanguage === "en" ? "FC state abnormal" : "飞控状态异常") : tr("fc_waiting")));
    setPreflightItem("#checkBattery", batteryReady, batteryReady ? `${Math.round(t.battery_percent)}% · ${tr("battery_normal")}` : tr("battery_low"));
    setPreflightItem("#checkFlow", navigationReady, gpsBaro
      ? (navigationReady ? `${t.gps_fix || "3D"} · EKF ${currentLanguage === "en" ? "position ready" : "位置就绪"}` : (gpsReady ? (currentLanguage === "en" ? "GPS fixed · Waiting for EKF position" : "GPS已定位 · 等待EKF位置") : (currentLanguage === "en" ? "Waiting for 3D fix and 6 satellites" : "等待3D定位与至少6颗卫星")))
      : (navigationReady ? `${Math.round(Number(t.optical_flow_quality))} · ${tr("flow_normal")}` : tr("flow_missing")));
    setPreflightItem("#checkRange", altitudeReady, gpsBaro
      ? (altitudeReady ? (currentLanguage === "en" ? "Barometer healthy" : "气压计正常") : (currentLanguage === "en" ? "Waiting for barometer health" : "等待气压计健康状态"))
      : (altitudeReady ? `${Number(t.height_agl).toFixed(2)}m · ${tr("range_normal")}` : tr("range_missing")));
    $("#preflightScore").textContent = `${passed}/4`;
    $("#preflightTitle").textContent = passed === 4 ? tr("check_complete") : `${passed}/4 ${tr("checks_blocked")}`;
    $("#preflightSubtitle").textContent = passed === 4 ? tr("safety_note") : `${passed}/4 ${tr("checks_ready")}`;
    const armed = t.armed === true;
    $("#armButton").textContent = armed ? tr("disarm") : (currentLanguage === "en" ? "Arm" : "解锁");
    $("#armButton").disabled = !controlAvailable || (!armed && passed !== 4);
    $("#takeoffButton").disabled = !controlAvailable || !takeoffEnabled || !armed || passed !== 4;
    $("#runPreflightCheck").disabled = !flightConnected;
    $("#controlLock").textContent = !flightConnected ? (currentLanguage === "en" ? "Device Offline" : "设备未连接") : controlAvailable ? tr("bench_control") : (currentLanguage === "en" ? "Safety Locked" : "安全锁定");
  }

  async function refreshControlStatus() {
    try {
      const response = await fetchWithTimeout("/api/control/status", { cache: "no-store" }, 1200);
      const status = await response.json();
      controlAvailable = Boolean(status.enabled);
      takeoffEnabled = Boolean(status.takeoff_enabled);
    } catch (_) {
      controlAvailable = false;
      takeoffEnabled = false;
    }
    if (latestTelemetry) updateTelemetry(latestTelemetry);
    setTimeout(refreshControlStatus, 2000);
  }

  function requireControlPin() {
    if (controlPin) return true;
    const entered = window.prompt(tr("enter_pin"), "");
    if (!entered) return false;
    controlPin = entered.trim();
    return true;
  }

  async function sendFlightCommand(action, params = {}) {
    if (!requireControlPin()) return false;
    try {
      const response = await fetchWithTimeout("/api/flight-command", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action, params, pin: controlPin }),
      }, 2500);
      const result = await response.json();
      if (!response.ok || !result.ok) {
        if (response.status === 403) controlPin = "";
        throw new Error(result.error || result.message || tr("command_failed"));
      }
      toast(`${tr("command_ok")} · ${action}`);
      return true;
    } catch (error) {
      toast(error.message || tr("command_failed"));
      return false;
    }
  }

  async function maintainControlHeartbeat() {
    if (controlPin) {
      try {
        await fetchWithTimeout("/api/flight-command", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ action: "heartbeat", params: {}, pin: controlPin }),
        }, 1200);
      } catch (_) {}
    }
    setTimeout(maintainControlHeartbeat, 1000);
  }

  async function refreshTelemetry() {
    try {
      const response = await fetchWithTimeout("/telemetry.json", { cache: "no-store" }, 1000);
      if (!response.ok) throw new Error(String(response.status));
      latestTelemetry = await response.json();
      updateTelemetry(latestTelemetry);
    } catch (_) {
      updateTelemetry({ connected: false, updated: 0 });
    } finally {
      setTimeout(refreshTelemetry, 500);
    }
  }

  function resizeOverlay() {
    const r = canvas.getBoundingClientRect();
    canvas.width = Math.round(r.width * devicePixelRatio);
    canvas.height = Math.round(r.height * devicePixelRatio);
  }

  function setOnline(online) {
    $("#linkState").classList.add("online");
    $("#linkState").innerHTML = `<i></i>${currentLanguage === "en" ? "Platform Online" : "平台在线"}`;
    $("#visionStatus").textContent = online ? tr("ai_running") : (currentLanguage === "en" ? "Vision Offline" : "识别未连接");
    $("#aiStateBadge").textContent = online ? tr("online") : tr("offline");
    $("#aiStateBadge").classList.toggle("online", online);
  }

  function drawBoxes(s) {
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    if (!s.width || !s.height) return;
    const sx = canvas.width / s.width;
    const sy = canvas.height / s.height;
    ctx.font = `${10 * devicePixelRatio}px "Segoe UI"`;
    for (const b of s.boxes || []) {
      const x = b.x1 * sx, y = b.y1 * sy;
      const w = (b.x2 - b.x1) * sx, h = (b.y2 - b.y1) * sy;
      const color = s.confirmed ? "#ff5364" : "#24cbd0";
      ctx.strokeStyle = color;
      ctx.lineWidth = 2 * devicePixelRatio;
      ctx.strokeRect(x, y, w, h);
      ctx.fillStyle = "rgba(0,0,0,.72)";
      ctx.fillRect(x, Math.max(0, y - 20 * devicePixelRatio), 100 * devicePixelRatio, 19 * devicePixelRatio);
      ctx.fillStyle = color;
      ctx.fillText(`${tr("suspected_person")} ${Math.round(b.confidence * 100)}%`, x + 5 * devicePixelRatio, Math.max(13 * devicePixelRatio, y - 6 * devicePixelRatio));
    }
  }

  function updateTarget(s) {
    if (!s.connected) {
      $("#aiFps").textContent = "--";
      $("#peopleTotal").textContent = "0";
      $("#missionTargetCount").textContent = "0";
      $("#targetPill").textContent = `0 ${tr("targets")}`;
      $("#targetStatus").textContent = currentLanguage === "en" ? "Vision service offline" : "识别服务未连接";
      $("#videoDetection").textContent = currentLanguage === "en" ? "OFFLINE" : "服务离线";
      $("#confidenceValue").textContent = "--";
      $("#confidenceBar").style.width = "0";
      $("#confirmTarget").disabled = true;
      $("#confirmTargetBottom").disabled = true;
      lastConfirmed = false;
      return;
    }
    const confidence = (s.boxes || []).reduce((n, b) => Math.max(n, b.confidence || 0), 0);
    $("#aiFps").textContent = Number(s.fps || 0).toFixed(1);
    $("#videoFps").textContent = "30 FPS";
    $("#peopleTotal").textContent = s.people || 0;
    if (!sharedMissionActive) $("#missionTargetCount").textContent = s.people || 0;
    $("#targetPill").textContent = `${s.people || 0} ${tr("targets")}`;
    $("#targetStatus").textContent = s.confirmed ? tr("person_found") : tr("monitoring");
    $("#videoDetection").textContent = s.confirmed ? tr("target_confirmed") : s.people ? tr("validating") : tr("scanning");
    $("#confidenceValue").textContent = confidence ? `${Math.round(confidence * 100)}%` : "--";
    $("#confidenceBar").style.width = `${Math.round(confidence * 100)}%`;
    $("#confirmTarget").disabled = !s.confirmed;
    $("#confirmTargetBottom").disabled = !s.confirmed;
    if (s.confirmed && !lastConfirmed) {
      const event = document.createElement("div");
      event.innerHTML = `<i class="alert"></i><p><strong>${tr("person_found")}</strong><small>${tr("evidence_saved")}</small></p><time>${tr("just_now")}</time>`;
      $("#eventStream").prepend(event);
    }
    lastConfirmed = Boolean(s.confirmed);
  }

  async function refresh() {
    const started = performance.now();
    try {
      const response = await fetchWithTimeout("/status.json", { cache: "no-store" }, 1000);
      if (!response.ok) throw new Error(String(response.status));
      const s = await response.json();
      latestDetection = s;
      const online = Boolean(s.connected && Date.now() / 1000 - Number(s.updated || 0) < 3);
      setOnline(online);
      $("#linkLatency").textContent = s.gateway_connected === false ? "--" : Math.max(1, Math.round(performance.now() - started));
      drawBoxes(s);
      updateTarget(s);
    } catch (_) {
      setOnline(false);
      latestDetection = { connected: false, boxes: [], people: 0, updated: 0 };
      updateTarget(latestDetection);
      $("#linkLatency").textContent = "--";
      ctx.clearRect(0, 0, canvas.width, canvas.height);
    } finally {
      setTimeout(refresh, 1000);
    }
  }

  function toast(message) {
    $("#toast").textContent = message;
    $("#toast").classList.add("show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => $("#toast").classList.remove("show"), 1800);
  }

  async function refreshSharedMission() {
    try {
      const response = await fetchWithTimeout("/api/base/status", { cache: "no-store" }, 1200);
      if (!response.ok) throw new Error(String(response.status));
      const snapshot = await response.json();
      const mission = snapshot.mission;
      sharedMissionActive = Boolean(mission);
      if (!mission) {
        $("#sharedMissionStatus").textContent = currentLanguage === "en" ? "Standby" : "待命";
        $("#sharedMissionTarget").textContent = "--";
        return;
      }
      const statusLabels = {
        prepared: currentLanguage === "en" ? "Prepared" : "待派发",
        queued: currentLanguage === "en" ? "Queued" : "已接收",
        executing: currentLanguage === "en" ? "Executing" : "执行中",
        completed: currentLanguage === "en" ? "Completed" : "已完成",
        aborted: currentLanguage === "en" ? "Aborted" : "已终止",
      };
      $("#missionTargetCount").textContent = "1";
      $("#sharedMissionStatus").textContent = statusLabels[mission.status] || mission.status || "--";
      const latitude = Number(mission.latitude);
      const longitude = Number(mission.longitude);
      $("#sharedMissionTarget").textContent = Number.isFinite(latitude) && Number.isFinite(longitude)
        ? `${latitude.toFixed(4)}, ${longitude.toFixed(4)}`
        : "--";
    } catch (_) {
      sharedMissionActive = false;
      $("#sharedMissionStatus").textContent = currentLanguage === "en" ? "Offline" : "指挥端离线";
      $("#sharedMissionTarget").textContent = "--";
    } finally {
      window.setTimeout(refreshSharedMission, 2500);
    }
  }

  document.querySelectorAll(".global-header nav button").forEach((button) => button.addEventListener("click", () => {
    const wasActive = button.classList.contains("active");
    document.querySelectorAll(".global-header nav button").forEach((b) => b.classList.remove("active"));
    button.classList.add("active");
    if (!wasActive) toast(`${button.textContent}${tr("coming_later")}`);
  }));
  $("#minimizeVideo").addEventListener("click", () => $("#videoConsole").classList.toggle("minimized"));
  $("#fullscreenVideo").addEventListener("click", async () => {
    try { await $("#videoBody").requestFullscreen(); } catch (_) { toast(tr("fullscreen_denied")); }
  });
  $("#confirmTarget").addEventListener("click", () => toast(tr("gps_required")));
  $("#confirmTargetBottom").addEventListener("click", () => toast(tr("gps_required")));
  $("#runPreflightCheck").addEventListener("click", () => {
    if (latestTelemetry) updateTelemetry(latestTelemetry);
    const passed = document.querySelectorAll("#preflightGrid .pass").length;
    toast(passed === 4 ? `${tr("check_complete")} · 4/4` : `${passed}/4 ${tr("checks_blocked")}`);
  });
  $("#armButton").addEventListener("click", async () => {
    const action = latestTelemetry?.armed === true ? "disarm" : "arm";
    await sendFlightCommand(action);
  });
  $("#takeoffButton").addEventListener("click", async () => {
    if (!takeoffEnabled) { toast(tr("takeoff_locked")); return; }
    const altitude = Number(window.prompt("起飞高度 (m)", "1.0"));
    if (!Number.isFinite(altitude)) return;
    if (latestTelemetry?.flight_mode !== "GUIDED") {
      const modeChanged = await sendFlightCommand("set_mode", { mode: "GUIDED" });
      if (!modeChanged) return;
      await new Promise((resolve) => setTimeout(resolve, 900));
      if (latestTelemetry?.flight_mode !== "GUIDED") {
        toast(currentLanguage === "en" ? "Waiting for GUIDED mode confirmation" : "等待飞控确认GUIDED模式");
        return;
      }
    }
    await sendFlightCommand("takeoff", { altitude });
  });
  $("#languageButton").addEventListener("click", (event) => {
    event.stopPropagation();
    const menu = $("#languageMenu");
    menu.hidden = !menu.hidden;
    $("#languageButton").setAttribute("aria-expanded", String(!menu.hidden));
  });
  document.querySelectorAll("[data-language]").forEach((button) => button.addEventListener("click", () => {
    applyLanguage(button.dataset.language);
    $("#languageMenu").hidden = true;
    $("#languageButton").setAttribute("aria-expanded", "false");
  }));
  document.addEventListener("click", () => {
    $("#languageMenu").hidden = true;
    $("#languageButton").setAttribute("aria-expanded", "false");
  });
  $("#zoomIn").addEventListener("click", () => map && map.zoomIn());
  $("#zoomOut").addEventListener("click", () => map && map.zoomOut());
  $("#locateMap").addEventListener("click", () => map && map.setView([30.5928, 114.3055], 7));
  window.addEventListener("resize", resizeOverlay);
  captureStaticText();
  applyLanguage(currentLanguage, false);
  resizeOverlay();
  initMap();
  refreshControlStatus();
  maintainControlHeartbeat();
  loadRuntimeConfig().finally(refresh);
  refreshSources();
  refreshTelemetry();
  refreshSharedMission();
})();
