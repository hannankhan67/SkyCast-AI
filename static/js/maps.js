/* SkyCast AI — Maps page
   Hourly timeline slider + RainViewer radar loading */
(function () {
  "use strict";
  var slider = document.getElementById("hourly-slider");
  var display = document.getElementById("hourly-display");
  if (!slider || !display) return;

  var hourly = [];
  var city = (document.querySelector('meta[name="city-key"]') || {}).content || "karachi";

  function loadHourly() {
    fetch("/api/weather?city=" + encodeURIComponent(city))
      .then(function (r) { return r.json(); })
      .then(function (w) {
        hourly = w.hourly || [];
        render(hourly, 0);
      })
      .catch(function () {});
  }

  function render(list, idx) {
    var i = parseInt(idx, 10);
    if (!list.length) { display.innerHTML = '<p class="text-sky-100/60 text-sm">No hourly data.</p>'; return; }
    display.innerHTML = list.map(function (h, n) {
      var active = n === i;
      return '<div class="min-w-[88px] rounded-2xl px-3 py-3 text-center flex flex-col items-center gap-2 transition-all ' +
        (active ? 'bg-white/20 border border-white/30 scale-105' : 'bg-white/10 border border-white/15 opacity-80') + '">' +
        '<span class="text-xs text-sky-100/80 font-medium">' + h.time + '</span>' +
        '<img src="' + h.icon + '" alt="' + h.label + '" class="w-8 h-8 object-contain">' +
        '<span class="text-lg font-light">' + h.temp + '°</span>' +
        '<span class="text-[11px] text-sky-100/60">' + h.precip + '%</span>' +
      '</div>';
    }).join("");
  }

  slider.addEventListener("input", function () { render(hourly, slider.value); });
  loadHourly();
})();

/* SkyCast AI — Live Lightning & Storm Cell Tracker (Leaflet overlay) */
(function () {
  "use strict";
  var mapEl = document.getElementById("lightning-map");
  var citySel = document.getElementById("lightning-city");
  var refreshBtn = document.getElementById("lightning-refresh");
  var meta = document.getElementById("lightning-meta");
  if (!mapEl || typeof L === "undefined") return;

  var map = L.map(mapEl, { zoomControl: true }).setView([30.3753, 69.3451], 5);
  L.tileLayer("https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png", {
    attribution: "&copy; OpenStreetMap &copy; CARTO", maxZoom: 19,
  }).addTo(map);

  var strikeLayer = L.layerGroup().addTo(map);
  var vectorLayer = L.layerGroup().addTo(map);

  function polarToXY(lat, lon, bearing, distKm) {
    var R = 6371, br = bearing * Math.PI / 180;
    var la1 = lat * Math.PI / 180, lo1 = lon * Math.PI / 180;
    var la2 = Math.asin(Math.sin(la1) * Math.cos(distKm / R) +
      Math.cos(la1) * Math.sin(distKm / R) * Math.cos(br));
    var lo2 = lo1 + Math.atan2(Math.sin(br) * Math.sin(distKm / R) * Math.cos(la1),
      Math.cos(distKm / R) - Math.sin(la1) * Math.sin(la2));
    return [la2 * 180 / Math.PI, lo2 * 180 / Math.PI];
  }

  function load() {
    if (!citySel) return;
    fetch("/api/lightning?city=" + encodeURIComponent(citySel.value))
      .then(function (r) { return r.json(); })
      .then(draw)
      .catch(function () { if (meta) meta.textContent = "Could not load storm data."; });
  }

  function draw(d) {
    strikeLayer.clearLayers();
    vectorLayer.clearLayers();
    if (!d.center) return;
    map.setView(d.center, 6);

    (d.strikes || []).forEach(function (s) {
      var r = Math.max(3, s.intensity / 6);
      var m = L.circleMarker([s.lat, s.lon], {
        color: "#fbbf24", fillColor: "#f59e0b", fillOpacity: 0.7, radius: r, weight: 1,
      }).addTo(strikeLayer);
      m.bindPopup("<b>Lightning strike</b><br>Intensity: " + s.intensity + "/100<br>Age: " + s.age_s + "s ago");
    });

    var cell = d.cell || { direction_deg: 0, speed_kmh: 20 };
    var tip = polarToXY(d.center[0], d.center[1], cell.direction_deg, cell.speed_kmh * 1.2);
    L.polyline([d.center, tip], { color: "#38bdf8", weight: 3, dashArray: "6 6" })
      .addTo(vectorLayer)
      .bindPopup("<b>Storm cell</b><br>Moving " + Math.round(cell.direction_deg) + "° at " + Math.round(cell.speed_kmh) + " km/h");

    if (meta) {
      meta.textContent = d.city + " · " + (d.strikes || []).length +
        " active strikes · cell " + Math.round(cell.speed_kmh) + " km/h " +
        Math.round(cell.direction_deg) + "° · updated " + d.generated_at;
    }
  }

  if (refreshBtn) refreshBtn.addEventListener("click", load);
  if (citySel) citySel.addEventListener("change", load);
  load();
})();
