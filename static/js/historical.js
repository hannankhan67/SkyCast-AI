/* SkyCast AI — Historical Comparison with 10/20/30-yr baselines + on-this-day */
(function () {
  "use strict";
  var citySel = document.getElementById("hist-city");
  var baseSel = document.getElementById("hist-baseline");
  var loadBtn = document.getElementById("hist-load");
  if (!loadBtn) return;

  var chart = null;

  function baselineData(d, key) {
    if (key === "10") return { data: d.baseline_10, label: "10-year avg", color: "rgba(251,191,36,0.9)" };
    if (key === "20") return { data: d.baseline_20, label: "20-year avg", color: "rgba(129,140,248,0.9)" };
    return { data: d.baseline_30, label: "30-year avg", color: "rgba(255,255,255,0.5)" };
  }

  function render(d) {
    var b = baselineData(d, baseSel.value);
    var canvas = document.getElementById("hist-chart");
    if (chart) chart.destroy();
    chart = new Chart(canvas, {
      type: "line",
      data: {
        labels: d.labels,
        datasets: [
          { label: "Current", data: d.current, borderColor: "rgba(125,211,252,0.95)", backgroundColor: "rgba(125,211,252,0.18)", fill: true, tension: 0.4, borderWidth: 2, pointRadius: 0 },
          { label: b.label, data: b.data, borderColor: b.color, borderDash: [6, 4], borderWidth: 2, pointRadius: 0, fill: false },
        ],
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        interaction: { mode: "index", intersect: false },
        plugins: { legend: { labels: { color: "rgba(224,242,254,0.75)" } },
          tooltip: { backgroundColor: "rgba(15,23,42,0.92)", padding: 12, cornerRadius: 12 } },
        scales: {
          x: { ticks: { color: "rgba(224,242,254,0.5)", maxTicksLimit: 8 }, grid: { color: "rgba(255,255,255,0.06)" } },
          y: { ticks: { color: "rgba(224,242,254,0.5)", callback: function (v) { return v + "°"; } }, grid: { color: "rgba(255,255,255,0.06)" } },
        },
      },
    });

    var av = document.getElementById("hist-anomaly-val");
    var as = document.getElementById("hist-anomaly-sub");
    if (av) { av.textContent = d.anomaly_label; av.className = "text-2xl font-light mt-1 " + (d.anomaly_30yr >= 0 ? "text-rose-200" : "text-emerald-200"); }
    if (as) as.textContent = "Current avg " + d.current_avg + "° vs " + d.baseline_30_avg + "°";

    var otd = d.on_this_day || {};
    var od = document.getElementById("hist-otd-date"); if (od) od.textContent = otd.date || "—";
    var oh = document.getElementById("hist-otd-high"); if (oh) oh.textContent = otd.record_high != null ? otd.record_high + "°" : "—";
    var ol = document.getElementById("hist-otd-low"); if (ol) ol.textContent = otd.record_low != null ? otd.record_low + "°" : "—";
    var list = document.getElementById("hist-otd-list");
    if (list) list.innerHTML = (otd.events || []).map(function (e) {
      return '<li class="flex gap-3"><span class="text-sky-300 font-semibold w-14 shrink-0">' + e.year + '</span><span>' + e.text + '</span></li>';
    }).join("");
  }

  function load() {
    loadBtn.disabled = true; loadBtn.textContent = "Loading...";
    fetch("/api/historical?city=" + encodeURIComponent(citySel.value))
      .then(function (r) { return r.json(); }).then(render)
      .catch(function () { var av = document.getElementById("hist-anomaly-val"); if (av) av.textContent = "Error"; })
      .finally(function () { loadBtn.disabled = false; loadBtn.textContent = "Load Chart"; });
  }

  loadBtn.addEventListener("click", load);
  if (citySel) citySel.addEventListener("change", load);
  if (baseSel) baseSel.addEventListener("change", load);
  load();
})();
