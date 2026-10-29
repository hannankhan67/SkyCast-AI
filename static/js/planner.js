/* SkyCast AI — Event & Outdoor Activity Planner */
(function () {
  "use strict";
  var eventSel = document.getElementById("planner-event");
  var citySel = document.getElementById("planner-city");
  var daysIn = document.getElementById("planner-days");
  var runBtn = document.getElementById("planner-run");
  if (!runBtn) return;

  var chart = null;
  var EVENT_KEYS = {
    "outdoor wedding": "wedding", "wedding": "wedding",
    "cricket match": "cricket", "cricket": "cricket",
    "drone flying": "drone", "drone": "drone",
    "camping": "camping", "marathon / run": "marathon", "marathon": "marathon", "run": "marathon",
    "hiking": "hiking",
  };

  function scoreColor(s) {
    if (s >= 8) return "rgba(52,211,153,0.85)";
    if (s >= 6.5) return "rgba(125,211,252,0.85)";
    if (s >= 4.5) return "rgba(251,191,36,0.85)";
    return "rgba(244,63,94,0.85)";
  }

  function render(d) {
    var rows = document.getElementById("planner-rows");
    rows.innerHTML = (d.days || []).map(function (r) {
      return '<tr class="border-b border-white/5 hover:bg-white/5">' +
        '<td class="py-3 pr-4">' + r.date + ' · ' + r.day + '</td>' +
        '<td class="py-3 pr-4">' + r.condition + '</td>' +
        '<td class="py-3 pr-4">' + r.max + '° / ' + r.min + '°</td>' +
        '<td class="py-3 pr-4">' + r.precip_prob + '%</td>' +
        '<td class="py-3 pr-4">' + r.wind + ' km/h</td>' +
        '<td class="py-3 pr-4 font-semibold">' + r.score + '/10</td>' +
        '<td class="py-3 verdict-' + r.verdict + '">' + r.verdict + '</td></tr>';
    }).join("");

    var best = document.getElementById("planner-best");
    if (d.best) {
      best.classList.remove("hidden");
      document.getElementById("planner-best-day").textContent = d.best.date + " (" + d.best.day + ")";
      document.getElementById("planner-best-score").textContent = d.best.score + "/10 · " + d.best.verdict;
    } else {
      best.classList.add("hidden");
    }

    var labels = (d.days || []).map(function (r) { return r.date; });
    var scores = (d.days || []).map(function (r) { return r.score; });
    var colors = (d.days || []).map(function (r) { return scoreColor(r.score); });
    var ctx = document.getElementById("planner-chart");
    if (chart) chart.destroy();
    chart = new Chart(ctx, {
      type: "bar",
      data: { labels: labels, datasets: [{ label: "Feasibility Score", data: scores, backgroundColor: colors, borderRadius: 8 }] },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: { legend: { display: false },
          tooltip: { backgroundColor: "rgba(15,23,42,0.92)", padding: 10, cornerRadius: 10 } },
        scales: {
          y: { beginAtZero: true, max: 10, ticks: { color: "rgba(224,242,254,0.6)" }, grid: { color: "rgba(255,255,255,0.06)" } },
          x: { ticks: { color: "rgba(224,242,254,0.6)" }, grid: { display: false } }
        }
      }
    });
  }

  function run() {
    var ev = EVENT_KEYS[(eventSel.value || "").toLowerCase()] || "cricket";
    var url = "/api/planner?city=" + encodeURIComponent(citySel.value) +
      "&event=" + encodeURIComponent(ev) + "&days=" + encodeURIComponent(daysIn.value);
    runBtn.disabled = true; runBtn.textContent = "Planning...";
    fetch(url).then(function (r) { return r.json(); }).then(render)
      .catch(function () { document.getElementById("planner-rows").innerHTML = '<tr><td colspan="7" class="py-4 text-rose-200">Could not load plan.</td></tr>'; })
      .finally(function () { runBtn.disabled = false; runBtn.textContent = "Plan Event"; });
  }

  runBtn.addEventListener("click", run);
  run();
})();
