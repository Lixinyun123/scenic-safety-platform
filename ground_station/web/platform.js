(function () {
  "use strict";

  const channels = ["station", "drone"];
  const states = new Map(channels.map((name) => [name, "checking"]));
  const runtime = window.SCENIC_PLATFORM_CONFIG || {};
  const apiBaseUrl = String(runtime.apiBaseUrl || "").replace(/\/$/, "");

  function apiUrl(path) {
    return apiBaseUrl ? `${apiBaseUrl}${path}` : path;
  }

  function toast(message) {
    let element = document.querySelector(".platform-toast");
    if (!element) {
      element = document.createElement("div");
      element.className = "platform-toast";
      document.body.appendChild(element);
    }
    element.textContent = message;
    element.classList.add("show");
    window.clearTimeout(toast.timer);
    toast.timer = window.setTimeout(() => element.classList.remove("show"), 2600);
  }

  async function fetchJson(url, options, timeout) {
    const controller = new AbortController();
    const timer = window.setTimeout(() => controller.abort(), timeout || 1600);
    try {
      const response = await fetch(url, { cache: "no-store", ...(options || {}), signal: controller.signal });
      if (!response.ok) throw new Error(String(response.status));
      return await response.json();
    } finally {
      window.clearTimeout(timer);
    }
  }

  function updateSummary() {
    const online = [...states.values()].filter((value) => value === "online").length;
    const configured = [...states.values()].filter((value) => value !== "unconfigured").length;
    const dot = document.getElementById("videoSummaryDot");
    const text = document.getElementById("videoSummaryText");
    dot.className = `dot ${online === 2 ? "green" : online ? "amber" : ""}`;
    text.textContent = online ? `${online} 路视频已接入` : configured ? "视频链路连接中" : "等待两路视频配置";
  }

  function setFeedState(feed, channel, state, detail) {
    states.set(channel, state);
    feed.dataset.videoState = state;
    const badge = feed.querySelector(".feed-top span");
    const labels = {
      checking: "VIDEO · 连接中",
      online: "LIVE · 实时",
      offline: "VIDEO · 离线",
      unconfigured: "VIDEO · 未接入",
    };
    badge.innerHTML = `<i class="dot ${state === "online" ? "green" : state === "checking" ? "amber" : ""}"></i>${labels[state]}`;
    let hint = feed.querySelector(".feed-hint");
    if (!hint) {
      hint = document.createElement("div");
      hint.className = "feed-hint";
      feed.appendChild(hint);
    }
    hint.innerHTML = `<strong>${state === "offline" ? "视频暂不可用" : state === "checking" ? "正在建立视频链路" : state === "unconfigured" ? "摄像头尚未接入平台" : ""}</strong><span>${detail || ""}</span>`;
    hint.hidden = !["offline", "checking", "unconfigured"].includes(state);
    updateSummary();
  }

  function mountFeed(channel, config) {
    const feed = document.querySelector(`[data-video-channel="${channel}"]`);
    if (!feed) return;
    const fallback = feed.querySelector("img");
    if (!config || !config.configured || !config.url) {
      setFeedState(feed, channel, "unconfigured", "需要摄像头独立 IP 与可播放的视频流地址");
      return;
    }

    setFeedState(feed, channel, "checking", "摄像头与页面相互独立，断线不会影响其他模块");
    let media;
    if (config.kind === "image") {
      media = document.createElement("img");
      media.alt = channel === "station" ? "基站实时摄像头" : "无人机实时摄像头";
    } else if (config.kind === "hls") {
      media = document.createElement("video");
      media.autoplay = true;
      media.muted = true;
      media.playsInline = true;
      media.controls = true;
    } else {
      media = document.createElement("iframe");
      media.title = channel === "station" ? "基站实时摄像头" : "无人机实时摄像头";
      media.allow = "autoplay; fullscreen";
    }
    media.className = "live-media";
    media.addEventListener("load", () => {
      fallback.hidden = true;
      setFeedState(feed, channel, "online", "");
    }, { once: true });
    media.addEventListener("error", () => {
      fallback.hidden = false;
      setFeedState(feed, channel, "offline", "检查摄像头地址、视频网关和图传链路");
    });
    media.src = config.url;
    feed.insertBefore(media, feed.firstChild);
  }

  async function loadVideoConfig() {
    const publicConfig = {
      station_video: runtime.stationVideo,
      drone_video: runtime.droneVideo,
    };
    if (publicConfig.station_video || publicConfig.drone_video) {
      mountFeed("station", publicConfig.station_video);
      mountFeed("drone", publicConfig.drone_video);
      return;
    }
    try {
      const config = await fetchJson(apiUrl("/api/platform/config"), null, 1800);
      mountFeed("station", config.station_video);
      mountFeed("drone", config.drone_video);
    } catch (_) {
      channels.forEach((channel) => {
        const feed = document.querySelector(`[data-video-channel="${channel}"]`);
        if (feed) setFeedState(feed, channel, "offline", "平台视频配置读取失败");
      });
    }
  }

  async function refreshMission() {
    try {
      const snapshot = await fetchJson(apiUrl("/api/base/status"), null, 1400);
      const button = document.getElementById("dispatchMission");
      const mission = snapshot.mission;
      if (!mission) {
        button.dataset.missionId = "";
        button.textContent = "确认事件后派遣无人机";
        return;
      }
      button.dataset.missionId = mission.mission_id || "";
      button.textContent = mission.status === "queued" ? "任务已进入无人机队列" : "派遣无人机执行任务";
      button.classList.toggle("queued", mission.status === "queued");
    } catch (_) {
      // Mission polling is independent from map and video rendering.
    }
  }

  async function dispatchMission() {
    const button = document.getElementById("dispatchMission");
    const missionId = button.dataset.missionId;
    if (!missionId) {
      toast("请先确认真实告警坐标并生成任务");
      return;
    }
    const token = window.prompt("请输入综合指挥操作令牌");
    if (!token) return;
    try {
      await fetchJson(apiUrl("/api/base/missions/dispatch"), {
        method: "POST",
        headers: { "Content-Type": "application/json", "Authorization": `Bearer ${token}` },
        body: JSON.stringify({ mission_id: missionId }),
      }, 2200);
      toast("任务已派发，无人机作业端可以查看任务详情");
      await refreshMission();
    } catch (_) {
      toast("任务派发失败，请检查令牌和无人机任务链路");
    }
  }

  document.getElementById("dispatchMission")?.addEventListener("click", dispatchMission);
  document.getElementById("fullscreenFeeds")?.addEventListener("click", async () => {
    const consoleElement = document.querySelector(".video-console");
    try { await consoleElement.requestFullscreen(); } catch (_) { toast("浏览器未允许全屏显示"); }
  });

  loadVideoConfig();
  refreshMission();
  window.setInterval(refreshMission, 3000);
}());
