(function () {
  "use strict";

  var mapRoot = document.getElementById("gis-map");
  var offlineNotice = document.getElementById("map-offline");
  if (!mapRoot) return;

  if (typeof window.L === "undefined") {
    offlineNotice.hidden = false;
    return;
  }

  var homeWgs84 = [30.5928, 114.3055];

  function outsideChina(lat, lon) {
    return lon < 72.004 || lon > 137.8347 || lat < 0.8293 || lat > 55.8271;
  }

  function transformLat(x, y) {
    var value = -100 + 2 * x + 3 * y + 0.2 * y * y + 0.1 * x * y + 0.2 * Math.sqrt(Math.abs(x));
    value += (20 * Math.sin(6 * x * Math.PI) + 20 * Math.sin(2 * x * Math.PI)) * 2 / 3;
    value += (20 * Math.sin(y * Math.PI) + 40 * Math.sin(y / 3 * Math.PI)) * 2 / 3;
    value += (160 * Math.sin(y / 12 * Math.PI) + 320 * Math.sin(y * Math.PI / 30)) * 2 / 3;
    return value;
  }

  function transformLon(x, y) {
    var value = 300 + x + 2 * y + 0.1 * x * x + 0.1 * x * y + 0.1 * Math.sqrt(Math.abs(x));
    value += (20 * Math.sin(6 * x * Math.PI) + 20 * Math.sin(2 * x * Math.PI)) * 2 / 3;
    value += (20 * Math.sin(x * Math.PI) + 40 * Math.sin(x / 3 * Math.PI)) * 2 / 3;
    value += (150 * Math.sin(x / 12 * Math.PI) + 300 * Math.sin(x / 30 * Math.PI)) * 2 / 3;
    return value;
  }

  function wgs84ToGcj02(point) {
    var lat = point[0], lon = point[1];
    if (outsideChina(lat, lon)) return point;
    var a = 6378245, ee = 0.00669342162296594323;
    var dLat = transformLat(lon - 105, lat - 35);
    var dLon = transformLon(lon - 105, lat - 35);
    var radLat = lat / 180 * Math.PI;
    var magic = Math.sin(radLat);
    magic = 1 - ee * magic * magic;
    var sqrtMagic = Math.sqrt(magic);
    dLat = dLat * 180 / ((a * (1 - ee)) / (magic * sqrtMagic) * Math.PI);
    dLon = dLon * 180 / (a / sqrtMagic * Math.cos(radLat) * Math.PI);
    return [lat + dLat, lon + dLon];
  }

  var home = wgs84ToGcj02(homeWgs84);
  var map = L.map(mapRoot, {
    center: home,
    zoom: 18,
    zoomControl: false,
    attributionControl: false,
    preferCanvas: true
  });

  var failedTiles = 0;
  var tiles = L.tileLayer("https://webst0{s}.is.autonavi.com/appmaptile?style=6&x={x}&y={y}&z={z}", {
    subdomains: ["1", "2", "3", "4"],
    maxZoom: 18,
    attribution: "高德卫星地图"
  });

  tiles.on("tileload", function () {
    offlineNotice.hidden = true;
  });
  tiles.on("tileerror", function () {
    failedTiles += 1;
    if (failedTiles >= 4) offlineNotice.hidden = false;
  });
  tiles.addTo(map);
  L.tileLayer("https://webst0{s}.is.autonavi.com/appmaptile?style=8&x={x}&y={y}&z={z}", {
    subdomains: ["1", "2", "3", "4"],
    maxZoom: 18,
    opacity: 0.95,
    attribution: "中文路网"
  }).addTo(map);

  document.querySelectorAll(".map-actions button").forEach(function (button, index) {
    button.addEventListener("click", function () {
      if (index === 0) map.zoomIn();
      if (index === 1) map.zoomOut();
      if (index === 2) map.flyTo(home, 18, { duration: 0.55 });
    });
  });

  window.addEventListener("resize", function () { map.invalidateSize(); });
  setTimeout(function () { map.invalidateSize(); }, 120);
}());
