/* SkyCast AI — Route Weather */
(function () {
  "use strict";
  var btn = document.getElementById("route-calc");
  if (!btn) return;

  function riskIcon(risk) {
    return { "fog": "🌫️", "heavy rain": "🌧️", "high crosswind": "💨", "extreme heat": "🔥" }[risk] || "⚠️";
  }

  function severityBadge(severity) {
    if (severity === "severe") return { cls: "bg-rose-400/20 border-rose-300/40 text-rose-200", label: "⚠️ Severe Risk" };
    if (severity === "caution") return { cls: "bg-amber-400/20 border-amber-300/40 text-amber-200", label: "⚠ Caution" };
    return { cls: "bg-emerald-400/20 border-emerald-300/40 text-emerald-200", label: "✓ Clear" };
  }

  function renderRoute(d) {
    document.getElementById("route-placeholder").classList.add("hidden");
    document.getElementById("route-result").classList.remove("hidden");
    document.getElementById("route-title").textContent = d.start + " → " + d.end + " (" + d.duration_hours + "h)";
    var badge = document.getElementById("route-risk-badge");
    var sb = severityBadge(d.overall_risk);
    badge.textContent = sb.label;
    badge.className = "px-3 py-1 rounded-full text-xs font-bold " + sb.cls;
    badge.classList.remove("hidden");
    document.getElementById("route-summary").textContent = d.risk_summary || "";

    var box = document.getElementById("route-points");
    var pointsHtml = "";
    for (var i = 0; i < (d.points || []).length; i++) {
      var p = d.points[i];
      var riskIcons = (p.risks || []).map(riskIcon).join(" ");
      var riskBorder = p.severity === "severe" ? "border-rose-400/40 bg-rose-400/10" :
                       p.severity === "caution" ? "border-amber-400/40 bg-amber-400/10" :
                       "border-white/15";
      var riskText = (p.risks && p.risks.length > 0) ? p.risks.join(", ") : "";
      var riskBadge = riskText ? '<span class="text-xs px-2 py-0.5 rounded-full ' + (p.severity === "severe" ? "bg-rose-400/20 text-rose-200" : "bg-amber-400/20 text-amber-200") + '">' + riskText + "</span>" : "";
      var iconSpan = riskIcons ? '<span class="text-sm">' + riskIcons + "</span>" : "";
      pointsHtml += '<div class="flex items-center justify-between rounded-2xl bg-white/10 border ' + riskBorder + ' px-5 py-3">' +
        '<div class="flex items-center gap-3">' +
        '<span class="text-sm font-medium text-sky-200">' + p.hour + "</span>" +
        '<span class="text-sm text-sky-100/80">' + p.condition + " · " + p.temp + "°C · " + p.wind + " km/h</span>" +
        "</div>" +
        '<div class="flex items-center gap-2">' + iconSpan + riskBadge + "</div>" +
        "</div>";
    }
    box.innerHTML = pointsHtml;

    var advBox = document.getElementById("route-advisories");
    if (d.risks && d.risks.length > 0) {
      advBox.classList.remove("hidden");
      var html = '<h4 class="text-sm font-bold text-sky-100 mb-3">Safety Advisories</h4>';
      var adviceMap = {
        "fog": "Slow down and use fog lights.",
        "heavy rain": "Reduce speed, headlights on, beware of aquaplaning.",
        "high crosswind": "Grip the wheel \u2014 strong lateral gusts.",
        "extreme heat": "Run A/C, carry water for the stretch."
      };
      for (var j = 0; j < d.risks.length; j++) {
        var r = d.risks[j];
        var cls = r.severity === "severe" ? "bg-rose-400/10 border border-rose-300/30" : "bg-amber-400/10 border border-amber-300/30";
        var txtCls = r.severity === "severe" ? "text-rose-200" : "text-amber-200";
        html += '<div class="mb-3 last:mb-0 p-3 rounded-xl ' + cls + '">';
        for (var k = 0; k < r.risks.length; k++) {
          var risk = r.risks[k];
          var icon = riskIcon(risk);
          html += '<p class="text-xs font-medium ' + txtCls + ' ' + (k > 0 ? "mt-1" : "") + '">' + icon + " " + (adviceMap[risk] || "") + "</p>";
        }
        html += '<p class="text-xs text-sky-100/50 mt-2">At ' + r.hour + " \u2014 " + r.risks.join(", ") + "</p>";
        html += "</div>";
      }
      advBox.innerHTML = html;
    } else {
      advBox.classList.add("hidden");
    }
  }

  btn.addEventListener("click", function () {
    var start = document.getElementById("route-start").value;
    var end = document.getElementById("route-end").value;
    if (start === end) return;
    var badge = document.getElementById("route-risk-badge");
    badge.classList.add("hidden");
    btn.disabled = true;
    btn.textContent = "Calculating...";
    fetch("/api/route?start=" + encodeURIComponent(start) + "&end=" + encodeURIComponent(end))
      .then(function (r) { if (!r.ok) throw new Error("bad response"); return r.json(); })
      .then(renderRoute)
      .catch(function () {
        document.getElementById("route-summary").textContent = "Could not load route data. Try again.";
        document.getElementById("route-placeholder").classList.remove("hidden");
        document.getElementById("route-result").classList.add("hidden");
      })
      .finally(function () { btn.disabled = false; btn.textContent = "Plan Route"; });
  });

  /* ===== Smart Commute Hazard Predictor ===== */
  var PRESETS = {
    "karachi-hyderabad": [
      { name: "Karachi Start", lat: 24.8607, lng: 67.0011, eta_minutes: 0 },
      { name: "Hyderabad Arrival", lat: 25.3960, lng: 68.3578, eta_minutes: 120 },
    ],
    "karachi-lahore": [
      { name: "Karachi Start", lat: 24.8607, lng: 67.0011, eta_minutes: 0 },
      { name: "Rohri Junction", lat: 27.6667, lng: 68.9000, eta_minutes: 480 },
      { name: "Multan Checkpoint", lat: 30.1575, lng: 71.5249, eta_minutes: 780 },
      { name: "Lahore Arrival", lat: 31.5204, lng: 74.3587, eta_minutes: 1140 },
    ],
    "lahore-islamabad": [
      { name: "Lahore Start", lat: 31.5204, lng: 74.3587, eta_minutes: 0 },
      { name: "Bhera Service Area", lat: 32.4833, lng: 72.9167, eta_minutes: 120 },
      { name: "Islamabad Arrival", lat: 33.6844, lng: 73.0479, eta_minutes: 220 },
    ],
  };

  var commuteBtn = document.getElementById("commute-check");
  if (commuteBtn) {
    var depInput = document.getElementById("commute-departure");
    if (depInput) depInput.value = new Date().toISOString().slice(0, 16);

    function hazardColor(level) {
      if (level === "High Risk") return "bg-rose-400/20 border-rose-300/40 text-rose-200";
      if (level === "Moderate Risk") return "bg-amber-400/20 border-amber-300/40 text-amber-200";
      return "bg-emerald-400/20 border-emerald-300/40 text-emerald-200";
    }

    function renderCommute(d) {
      document.getElementById("commute-placeholder").classList.add("hidden");
      var result = document.getElementById("commute-result");
      result.classList.remove("hidden");
      var badge = document.getElementById("commute-badge");
      badge.textContent = d.has_hazards ? "HAZARDS DETECTED" : "ROUTE CLEAR";
      badge.className = "inline-block px-4 py-1.5 rounded-full text-xs font-bold tracking-widest border " + (d.has_hazards ? "bg-rose-400/20 border-rose-300/40 text-rose-200" : "bg-emerald-400/20 border-emerald-300/40 text-emerald-200");
      document.getElementById("commute-recommendation").textContent = d.recommendation;
      var tl = document.getElementById("commute-timeline");
      var html = "";
      for (var i = 0; i < (d.route_timeline || []).length; i++) {
        var item = d.route_timeline[i];
        var w = item.weather || {};
        var hazardCls = hazardColor(item.hazard_level);
        var msgCls = item.hazard_level === "Safe" ? "text-emerald-300" : "text-rose-300";
        var temp = w.temp != null ? w.temp + "°C" : "—";
        var rain = w.precip_prob != null ? w.precip_prob + "%" : "—";
        var wind = w.wind_speed != null ? w.wind_speed : "—";
        html += '<div class="flex items-center justify-between rounded-2xl bg-white/10 border ' + hazardCls + ' px-5 py-3">';
        html += '<div><span class="text-sm font-medium text-sky-200">' + item.waypoint + '</span> <span class="text-xs text-sky-100/60">(' + item.eta + ')</span>';
        html += '<p class="text-xs ' + msgCls + '">' + item.hazard_msg + '</p></div>';
        html += '<div class="text-right"><span class="text-sm font-light">' + temp + '</span>';
        html += '<p class="text-[11px] text-sky-100/60">Rain ' + rain + ' · Wind ' + wind + '</p></div>';
        html += '</div>';
      }
      tl.innerHTML = html;
    }

    commuteBtn.addEventListener("click", function () {
      var preset = document.getElementById("commute-preset").value;
      var waypoints = PRESETS[preset] || PRESETS["karachi-hyderabad"];
      var dep = document.getElementById("commute-departure").value;
      if (!dep) { alert("Please select a departure time."); return; }
      commuteBtn.disabled = true;
      commuteBtn.textContent = "Analyzing...";
      fetch("/api/route/smart-commute", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ departure_time: dep, waypoints: waypoints }),
      })
        .then(function (r) { if (!r.ok) throw new Error("bad response"); return r.json(); })
        .then(renderCommute)
        .catch(function () { alert("Could not analyze route. Try again."); })
        .finally(function () { commuteBtn.disabled = false; commuteBtn.textContent = "Analyze Route Hazards"; });
    });
  }
})();
