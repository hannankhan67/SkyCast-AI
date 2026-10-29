/* SkyCast AI — Air Quality Dashboard (/aqi) */
(function () {
  "use strict";
  var citySel = document.getElementById("aqi-city");
  var loadBtn = document.getElementById("aqi-load");
  var chartInst = null;
  if (!citySel || !loadBtn) return;

  function categoryStyle(aqi) {
    aqi = Number(aqi) || 0;
    if (aqi <= 50) return ["Good", "bg-emerald-400/20 border-emerald-300/40 text-emerald-200"];
    if (aqi <= 100) return ["Moderate", "bg-amber-400/20 border-amber-300/40 text-amber-200"];
    if (aqi <= 150) return ["Unhealthy (Sensitive)", "bg-orange-400/20 border-orange-300/40 text-orange-200"];
    if (aqi <= 200) return ["Unhealthy", "bg-rose-400/20 border-rose-300/40 text-rose-200"];
    if (aqi <= 300) return ["Very Unhealthy", "bg-red-400/20 border-red-300/40 text-red-200"];
    return ["Hazardous", "bg-fuchsia-400/20 border-fuchsia-300/40 text-fuchsia-200"];
  }

  function render(d) {
    var hourly = d.hourly || [];
    var cur = document.getElementById("aqi-current");
    var cat = document.getElementById("aqi-cat");
    var style = categoryStyle(d.current_aqi);
    if (cur) {
      cur.textContent = d.current_aqi;
      cur.className = "text-4xl font-light mt-1 " + style[1].split(" ")[2];
    }
    if (cat) {
      cat.textContent = style[0];
      cat.className = "text-sm mt-1 " + style[1].split(" ")[2];
    }
    var peak = document.getElementById("aqi-peak"); if (peak) peak.textContent = d.peak_aqi != null ? d.peak_aqi : "—";
    var src = document.getElementById("aqi-source"); if (src) src.textContent = d.source || "—";

    // Light 3-point smoothing for clean, professional curves.
    function smooth(arr) {
      var out = arr.slice();
      for (var i = 1; i < out.length - 1; i++) {
        if (out[i - 1] == null || out[i + 1] == null) continue;
        out[i] = (out[i - 1] + 2 * out[i] + out[i + 1]) / 4;
      }
      return out;
    }
    var labels = hourly.map(function (h) { return h.time; });
    var pm25 = smooth(hourly.map(function (h) { return h.pm2_5; }));
    var pm10 = smooth(hourly.map(function (h) { return h.pm10; }));
    var o3 = smooth(hourly.map(function (h) { return h.o3; }));
    var no2 = smooth(hourly.map(function (h) { return h.no2; }));
    var aqiVals = smooth(hourly.map(function (h) { return h.us_aqi; }));

    var canvas = document.getElementById("aqi-chart");
    if (chartInst) chartInst.destroy();
    var grad = canvas.getContext("2d").createLinearGradient(0, 0, 0, 420);
    grad.addColorStop(0, "rgba(125,211,252,0.18)");
    grad.addColorStop(1, "rgba(129,140,248,0.02)");
    chartInst = new Chart(canvas, {
      type: "line",
      data: {
        labels: labels,
        datasets: [
          { label: "PM2.5 (µg/m³)", data: pm25, borderColor: "rgba(125,211,252,1)", backgroundColor: grad, fill: true, tension: 0.4, borderWidth: 3, borderCapStyle: "round", borderJoinStyle: "round", pointRadius: 0, pointHoverRadius: 5, spanGaps: true, yAxisID: "y" },
          { label: "PM10 (µg/m³)", data: pm10, borderColor: "rgba(16,185,129,0.55)", fill: false, tension: 0.35, borderWidth: 2, borderCapStyle: "round", borderJoinStyle: "round", pointRadius: 0, pointHoverRadius: 5, spanGaps: true, yAxisID: "y" },
          { label: "O₃ (µg/m³)", data: o3, borderColor: "rgba(251,191,36,0.6)", fill: false, tension: 0.35, borderWidth: 2, borderCapStyle: "round", borderJoinStyle: "round", pointRadius: 0, pointHoverRadius: 5, spanGaps: true, yAxisID: "y" },
          { label: "NO₂ (µg/m³)", data: no2, borderColor: "rgba(168,85,247,0.6)", fill: false, tension: 0.35, borderWidth: 2, borderCapStyle: "round", borderJoinStyle: "round", pointRadius: 0, pointHoverRadius: 5, spanGaps: true, yAxisID: "y" },
          { label: "US AQI", data: aqiVals, borderColor: "rgba(252,103,103,0.95)", fill: false, tension: 0.45, borderWidth: 3, borderCapStyle: "round", borderJoinStyle: "round", pointRadius: 3, pointHoverRadius: 6, pointBackgroundColor: "rgba(252,103,103,1)", spanGaps: true, yAxisID: "y1" },
        ],
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        interaction: { mode: "index", intersect: false },
        plugins: { legend: { display: false },
          tooltip: { backgroundColor: "rgba(15,23,42,0.92)", padding: 12, cornerRadius: 12 } },
        scales: {
          x: { ticks: { color: "rgba(224,242,254,0.55)", maxTicksLimit: 12 }, grid: { color: "rgba(255,255,255,0.06)" } },
          y: { ticks: { color: "rgba(224,242,254,0.55)" }, grid: { color: "rgba(255,255,255,0.06)" } },
          y1: { type: "linear", position: "right", grid: { drawOnChartArea: false }, ticks: { color: "rgba(252,103,103,0.8)" }, title: { display: true, text: "AQI", color: "rgba(252,103,103,0.8)" } },
        },
      },
    });

    var rows = document.getElementById("aqi-rows");
    if (rows) {
      rows.innerHTML = hourly.map(function (h) {
        return '<tr class="border-b border-white/5 hover:bg-white/5">' +
          '<td class="py-2 pr-4">' + h.time + '</td>' +
          '<td class="py-2 pr-4">' + h.pm2_5 + '</td>' +
          '<td class="py-2 pr-4">' + h.pm10 + '</td>' +
          '<td class="py-2 pr-4">' + h.o3 + '</td>' +
          '<td class="py-2 pr-4">' + h.no2 + '</td>' +
          '<td class="py-2 font-semibold">' + h.us_aqi + '</td></tr>';
      }).join("");
    }
  }

  function load() {
    loadBtn.disabled = true; loadBtn.textContent = "Loading...";
    fetch("/api/v1/aqi/forecast?city=" + encodeURIComponent(citySel.value))
      .then(function (r) { if (!r.ok) throw new Error("fail"); return r.json(); })
      .then(render)
      .catch(function () { var c = document.getElementById("aqi-current"); if (c) c.textContent = "Error"; })
      .finally(function () { loadBtn.disabled = false; loadBtn.textContent = "Refresh"; });
  }

  loadBtn.addEventListener("click", load);
  citySel.addEventListener("change", load);
  load();
})();
