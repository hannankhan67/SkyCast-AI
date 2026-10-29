/* SkyCast AI — Live Weather page
   Fills the current-condition hero, 24-hour strip, stats and 7-day grid
   from /api/weather. Honors a ?city= query param for deep links. */
(function () {
  "use strict";
  var $ = function (s) { return document.querySelector(s); };

  function uvLabel(v) {
    if (v < 3) return "Low";
    if (v < 6) return "Moderate";
    if (v < 8) return "High";
    if (v < 11) return "Very High";
    return "Extreme";
  }

  function renderWeather(w) {
    $("#city-name").textContent = w.city;
    $("#temp").textContent = w.temp + "°";
    $("#condition").textContent = w.condition;
    $("#feels-like").textContent = w.feels_like + "°";
    $("#humidity").textContent = w.humidity + "%";
    $("#wind").textContent = w.wind + " km/h";
    $("#uv").textContent = w.uv + " · " + uvLabel(w.uv);
    $("#pressure").textContent = w.pressure + " hPa";
    $("#visibility").textContent = w.visibility + " km";
    $("#aqi").textContent = w.aqi ? w.aqi + " AQI" : "—";

    var icon = $("#weather-icon");
    if (icon) icon.src = w.icon;

    var badge = $("#data-source");
    if (badge) {
      var live = w.live !== false;
      badge.textContent = live ? "LIVE" : "SIMULATED";
      badge.className =
        "inline-flex items-center rounded-full px-3 py-1 text-xs font-bold tracking-widest border " +
        (live
          ? "bg-emerald-400/20 border-emerald-300/40 text-emerald-200"
          : "bg-amber-400/20 border-amber-300/40 text-amber-200");
    }

    var up = $("#update-time");
    if (up) up.textContent = (w.live !== false ? "Open-Meteo" : w.source) + " · Updated " + w.updated;

    var cityShort = (w.city || "").split(",")[0];
    var sky = (w.condition || "").toLowerCase();
    sky = sky === "clear sky" ? "clear" : sky;
    var line = $("#sky-line-weather");
    if (line) line.textContent = "The sky is " + sky + " in " + cityShort + " today.";

    renderHourly(w.hourly || []);
    renderForecast(w.forecast || []);
    renderAqiBadge(w.aqi);
    loadAqiChart();
    loadMiniHist();
  }

  function renderAqiBadge(aqiNum) {
    var el = document.getElementById("aqi-badge");
    if (!el) return;
    if (aqiNum == null || aqiNum === "—") {
      el.textContent = "AQI —";
      el.className = "inline-flex items-center rounded-full px-3 py-1 text-xs font-bold border bg-white/10 border-white/20 text-sky-100/50";
      return;
    }
    var label, colorCls;
    if (aqiNum <= 50) { label = "Good"; colorCls = "bg-emerald-400/20 border-emerald-300/40 text-emerald-200"; }
    else if (aqiNum <= 100) { label = "Moderate"; colorCls = "bg-amber-400/20 border-amber-300/40 text-amber-200"; }
    else if (aqiNum <= 150) { label = "Unhealthy SG"; colorCls = "bg-orange-400/20 border-orange-300/40 text-orange-200"; }
    else if (aqiNum <= 200) { label = "Unhealthy"; colorCls = "bg-rose-400/20 border-rose-300/40 text-rose-200"; }
    else if (aqiNum <= 300) { label = "Very Unhealthy"; colorCls = "bg-purple-400/20 border-purple-300/40 text-purple-200"; }
    else { label = "Hazardous"; colorCls = "bg-red-800/30 border-red-600/40 text-red-200"; }
    el.innerHTML = aqiNum + " · <span class=\"font-semibold\">" + label + "</span>";
    el.className = "inline-flex items-center rounded-full px-3 py-1 text-xs font-bold tracking-widest border " + colorCls;
  }

  function renderHourly(list) {
    var grid = $("#hourly-grid");
    if (!grid) return;
    grid.innerHTML = list.length ? list.map(function (h) {
      return (
        '<div class="min-w-[96px] rounded-2xl bg-white/10 backdrop-blur-lg border border-white/20 px-4 py-4 text-center flex flex-col items-center gap-2">' +
          '<span class="text-xs text-sky-100/70 font-medium">' + h.time + "</span>" +
          '<img src="' + h.icon + '" alt="' + h.label + '" class="w-9 h-9 object-contain">' +
          '<span class="text-xl font-light">' + h.temp + "°</span>" +
          '<span class="text-[11px] text-sky-100/60">' + h.precip + "% precip</span>" +
        "</div>"
      );
    }).join("") : '<p class="text-sky-100/60 text-sm">Hourly data unavailable.</p>';
  }

  function renderForecast(list) {
    var grid = $("#forecast-grid");
    if (!grid) return;
    grid.innerHTML = list.map(function (d) {
      return (
        '<div class="rounded-3xl bg-white/10 backdrop-blur-lg border border-white/20 p-4 md:p-5 text-center transition-all duration-300 hover:bg-white/15 hover:-translate-y-1">' +
          '<p class="text-xs md:text-sm font-semibold tracking-widest uppercase text-sky-100">' + d.day + "</p>" +
          '<img src="' + d.icon + '" alt="' + d.condition + '" loading="lazy" class="w-12 h-12 md:w-14 md:h-14 mx-auto my-3 object-contain">' +
          '<p class="text-lg md:text-xl font-light"><span class="font-semibold">' + d.max + "°</span>" +
          '<span class="text-sky-100/60 ml-1 text-sm">' + d.min + "°</span></p>" +
          '<p class="text-xs text-sky-100/70 mt-1 truncate">' + d.condition + "</p>" +
        "</div>"
      );
    }).join("");
  }

  function loadMiniHist() {
    if (typeof Chart === "undefined") return;
    var canvas = document.getElementById("mini-hist-chart");
    if (!canvas) return;
    var ctx = canvas.getContext("2d");
    var sel2 = document.getElementById("city-select");
    var city = sel2 ? sel2.value : "karachi";
    fetch("/api/historical?city=" + encodeURIComponent(city))
      .then(function (r) { if (!r.ok) throw new Error("hist fetch failed"); return r.json(); })
      .then(function (d) {
        var labels = d.labels || [];
        var cur = d.current || d.baseline_30 || [];
        var avg = d.average || d.baseline_30 || [];
        new Chart(ctx, {
          type: "bar",
          data: {
            labels: labels,
            datasets: [
              { label: "Current", data: cur, backgroundColor: "rgba(125, 211, 252, 0.75)", borderRadius: 3, barThickness: 12 },
              { label: "Avg", data: avg, backgroundColor: "rgba(255,255,255,0.15)", borderRadius: 3, barThickness: 12 }
            ]
          },
          options: {
            responsive: true, maintainAspectRatio: false,
            plugins: { legend: { labels: { color: "rgba(224, 242, 254, 0.75)", font: { family: "Inter", size: 11 } } }, tooltip: { backgroundColor: "rgba(15,23,42,0.92)", borderColor: "rgba(255,255,255,0.15)", borderWidth: 1, titleColor: "#e0f2fe", bodyColor: "#bae6fd", padding: 10, cornerRadius: 10 } },
            scales: { x: { grid: { display: false }, ticks: { color: "rgba(224, 242, 254, 0.55)", font: { family: "Inter", size: 11 } } }, y: { grid: { color: "rgba(255,255,255,0.06)" }, ticks: { color: "rgba(224, 242, 254, 0.55)", font: { family: "Inter", size: 11 } } } }
          }
        });
      })
      .catch(function () {});
  }

  var aqiChartInstance = null;
  function loadAqiChart() {
    if (typeof Chart === "undefined") return;
    var canvas = document.getElementById("aqi-chart");
    if (!canvas) return;
    if (aqiChartInstance) aqiChartInstance.destroy();
    var ctx = canvas.getContext("2d");
    var sel = document.getElementById("city-select");
    var city = sel ? sel.value : "karachi";
    fetch("/api/v1/aqi/forecast?city=" + encodeURIComponent(city))
      .then(function (r) { if (!r.ok) throw new Error("aqi fetch failed"); return r.json(); })
      .then(function (d) {
        var hourly = d.hourly || d.points || [];
        var sourceBadge = document.getElementById("aqi-source");
        if (sourceBadge) {
          sourceBadge.textContent = d.live ? "Live data" : "Simulated";
          sourceBadge.className = "text-xs " + (d.live ? "text-emerald-300" : "text-amber-300");
        }
        // Keep the badge in sync with the chart's actual current AQI.
        var cur = d.current_aqi != null ? d.current_aqi : (hourly.length ? hourly[0].us_aqi : null);
        if (cur != null) renderAqiBadge(cur);
        // Light 3-point smoothing keeps the curves clean instead of spiky.
        function smooth(arr) {
          var out = arr.slice();
          for (var i = 1; i < out.length - 1; i++) {
            if (out[i - 1] == null || out[i + 1] == null) continue;
            out[i] = (out[i - 1] + 2 * out[i] + out[i + 1]) / 4;
          }
          return out;
        }
        var labels = hourly.map(function (h) { return h.time || h.hour; });
        var pm25 = smooth(hourly.map(function (h) { return h.pm2_5 || h.pm25; }));
        var pm10 = smooth(hourly.map(function (h) { return h.pm10; }));
        var o3 = smooth(hourly.map(function (h) { return h.o3 || h.ozone; }));
        var no2 = smooth(hourly.map(function (h) { return h.no2 || h.nitrogen_dioxide; }));
        var aqiVals = smooth(hourly.map(function (h) { return h.us_aqi || h.aqi; }));
        var grad = ctx.createLinearGradient(0, 0, 0, 360);
        grad.addColorStop(0, "rgba(125, 211, 252, 0.18)");
        grad.addColorStop(1, "rgba(129, 140, 248, 0.02)");
        aqiChartInstance = new Chart(ctx, {
          type: "line",
          data: { labels: labels, datasets: [
            { label: "PM2.5 (µg/m³)", data: pm25, borderColor: "rgba(125, 211, 252, 1)", backgroundColor: grad, fill: true, tension: 0.4, borderWidth: 3, borderCapStyle: "round", borderJoinStyle: "round", pointRadius: 0, pointHoverRadius: 5, spanGaps: true, yAxisID: "y" },
            { label: "PM10 (µg/m³)", data: pm10, borderColor: "rgba(16, 185, 129, 0.55)", fill: false, tension: 0.35, borderWidth: 2, borderCapStyle: "round", borderJoinStyle: "round", pointRadius: 0, pointHoverRadius: 5, spanGaps: true, yAxisID: "y" },
            { label: "O₃ (µg/m³)", data: o3, borderColor: "rgba(251, 191, 36, 0.6)", fill: false, tension: 0.35, borderWidth: 2, borderCapStyle: "round", borderJoinStyle: "round", pointRadius: 0, pointHoverRadius: 5, spanGaps: true, yAxisID: "y" },
            { label: "NO₂ (µg/m³)", data: no2, borderColor: "rgba(168, 85, 247, 0.6)", fill: false, tension: 0.35, borderWidth: 2, borderCapStyle: "round", borderJoinStyle: "round", pointRadius: 0, pointHoverRadius: 5, spanGaps: true, yAxisID: "y" },
            { label: "US AQI", data: aqiVals, borderColor: "rgba(252, 103, 103, 0.95)", fill: false, tension: 0.45, borderWidth: 3, borderCapStyle: "round", borderJoinStyle: "round", pointRadius: 3, pointHoverRadius: 6, pointBackgroundColor: "rgba(252, 103, 103, 1)", spanGaps: true, yAxisID: "y1" }
          ] },
          options: {
            responsive: true, maintainAspectRatio: false,
            interaction: { mode: "index", intersect: false },
            plugins: { legend: { labels: { color: "rgba(224, 242, 254, 0.75)", font: { family: "Inter, sans-serif", size: 12 } } }, tooltip: { backgroundColor: "rgba(15, 23, 42, 0.92)", borderColor: "rgba(255,255,255,0.15)", borderWidth: 1, titleColor: "#e0f2fe", bodyColor: "#bae6fd", padding: 12, cornerRadius: 12 } },
            scales: {
              x: { ticks: { color: "rgba(224, 242, 254, 0.55)", maxTicksLimit: 8, font: { family: "Inter" } }, grid: { color: "rgba(255,255,255,0.06)" } },
              y: { ticks: { color: "rgba(224, 242, 254, 0.55)", font: { family: "Inter" } }, grid: { color: "rgba(255,255,255,0.06)" }, position: "left" },
              y1: { type: "linear", position: "right", grid: { drawOnChartArea: false, color: "rgba(255,255,255,0.03)" }, ticks: { color: "rgba(224, 242, 254, 0.55)", font: { family: "Inter" } }, title: { display: true, text: "AQI", color: "rgba(224, 242, 254, 0.65)" } }
            }
          }
        });
      })
      .catch(function () {});
  }

  function loadWeather(city) {
    fetch("/api/weather?city=" + encodeURIComponent(city))
      .then(function (r) { if (!r.ok) throw new Error("bad response"); return r.json(); })
      .then(renderWeather)
      .catch(function (err) { console.error("Weather load failed:", err); });
  }

  var select = $("#city-select");
  // honor ?city= deep links (Dashboard cards link here)
  var params = new URLSearchParams(window.location.search);
  var pre = params.get("city");
  if (pre && select) {
    var match = Array.prototype.slice.call(select.options).some(function (o) { return o.value === pre; });
    if (match) select.value = pre;
  }
  loadWeather(select ? select.value : "karachi");

  if (select) {
    select.addEventListener("change", function (e) { loadWeather(e.target.value); });
  }
})();
