/* SkyCast AI — API Portal (key management + interactive playground + metrics) */
(function () {
  "use strict";
  var createBtn = document.getElementById("create-key-btn");
  if (createBtn) {
    createBtn.addEventListener("click", function () {
      fetch("/api/keys", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: "Default" }) })
        .then(function (r) { return r.json(); })
        .then(function (d) {
          alert("New API Key (save it now):\n" + d.key);
          location.reload();
        })
        .catch(function () { alert("Failed to create key."); });
    });
  }
  document.querySelectorAll("[data-delete]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var id = btn.getAttribute("data-delete");
      fetch("/api/keys/" + id, { method: "DELETE" })
        .then(function (r) { return r.json(); })
        .then(function (d) { if (d.revoked) location.reload(); });
    });
  });

  /* --- Interactive Playground --- */
  var epSel = document.getElementById("pg-endpoint");
  var cityIn = document.getElementById("pg-city");
  var runBtn = document.getElementById("pg-run");
  var resp = document.getElementById("pg-response");
  var snip = document.getElementById("pg-snippet");
  if (!runBtn) return;

  function buildSnippet() {
    var ep = epSel.value, city = (cityIn.value || "karachi").trim();
    var url = "https://skycast.ai/api/v1/" + ep + "?city=" + encodeURIComponent(city);
    return {
      curl: "curl -X GET '" + url + "' \\\n  -H 'X-API-Key: YOUR_API_KEY'",
      js: "fetch('" + url + "', {\n  headers: { 'X-API-Key': 'YOUR_API_KEY' }\n})\n  .then(r => r.json())\n  .then(console.log);",
      python: "import requests\nr = requests.get('" + url + "', headers={'X-API-Key': 'YOUR_API_KEY'})\nprint(r.json())",
    };
  }

  function showSnippet(lang) {
    document.querySelectorAll(".pg-tab").forEach(function (b) {
      b.classList.toggle("bg-white/15", b.getAttribute("data-lang") === lang);
      b.classList.toggle("bg-white/10", b.getAttribute("data-lang") !== lang);
    });
    snip.textContent = buildSnippet()[lang] || "";
  }

  document.querySelectorAll(".pg-tab").forEach(function (b) {
    b.addEventListener("click", function () { showSnippet(b.getAttribute("data-lang")); });
  });
  showSnippet("curl");

  function runPlayground() {
    runBtn.disabled = true; runBtn.textContent = "Sending...";
    fetch("/api/playground", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ endpoint: epSel.value, city: cityIn.value }),
    })
      .then(function (r) { return r.json().then(function (j) { return { ok: r.ok, j: j }; }); })
      .then(function (o) {
        resp.textContent = JSON.stringify(o.j, null, 2);
        resp.className = "text-xs font-mono whitespace-pre-wrap " + (o.ok ? "text-emerald-200" : "text-rose-200");
      })
      .catch(function () { resp.textContent = "// request failed"; resp.className = "text-xs font-mono whitespace-pre-wrap text-rose-200"; })
      .finally(function () { runBtn.disabled = false; runBtn.textContent = "Send"; });
  }

  runBtn.addEventListener("click", runPlayground);
  if (cityIn) cityIn.addEventListener("keydown", function (e) { if (e.key === "Enter") runPlayground(); });

  /* --- Usage metrics chart --- */
  var usageCanvas = document.getElementById("pg-usage-chart");
  if (usageCanvas && typeof Chart !== "undefined") {
    fetch("/api/v1/metrics").then(function (r) { return r.json(); }).then(function (m) {
      var d = m.daily_requests || [];
      var errs = (m.status_breakdown && m.status_breakdown["500"]) || 0;
      new Chart(usageCanvas, {
        type: "line",
        data: {
          labels: d.map(function (x) { return x.date; }),
          datasets: [{
            label: "Requests", data: d.map(function (x) { return x.requests; }),
            borderColor: "rgba(125,211,252,0.95)", backgroundColor: "rgba(125,211,252,0.18)",
            fill: true, tension: 0.4, borderWidth: 2, pointRadius: 3,
          }],
        },
        options: {
          responsive: true, maintainAspectRatio: false,
          plugins: { legend: { display: false } },
          scales: {
            x: { ticks: { color: "rgba(224,242,254,0.55)" }, grid: { color: "rgba(255,255,255,0.06)" } },
            y: { ticks: { color: "rgba(224,242,254,0.55)" }, grid: { color: "rgba(255,255,255,0.06)" } },
          },
        },
      });
      var t = document.getElementById("pg-today"); if (t) t.textContent = m.total_today;
      var e = document.getElementById("pg-err"); if (e) e.textContent = errs;
      var q = document.getElementById("pg-quota"); if (q) q.textContent = (m.remaining_quota != null ? m.remaining_quota : "—");
    }).catch(function () {});
  }
})();
