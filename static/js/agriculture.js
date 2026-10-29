/* SkyCast AI — Agriculture Analytics */
(function () {
  "use strict";

  var btn = document.getElementById("ag-calc");
  if (!btn) return;

  var moistEl = document.getElementById("ag-moist");
  var evapEl  = document.getElementById("ag-evap");
  var et0El   = document.getElementById("ag-et0-method");
  var frostEl = document.getElementById("ag-frost");
  var advice  = document.getElementById("ag-advice-text");
  var urgency = document.getElementById("ag-urgency");
  var tips    = document.getElementById("ag-tips");
  var fill    = document.getElementById("moisture-fill");

  function setMoisturePct(pct) {
    if (!fill) return;
    fill.style.width = Math.max(5, pct) + "%";
  }

  function urgencyClass(level) {
    if (level === "high")   { return "urgency-high"; }
    if (level === "medium") { return "urgency-medium"; }
    return "urgency-low";
  }

  function setTips(data) {
    if (!tips) return;
    var netMm   = Number(data.net_irrigation_mm);
    var netL    = Number(data.net_irrigation_l_m2);
    var tip     = data.water_saving_tip || "";
    tips.innerHTML = ""
      + '<div class="cmd-card rounded-xl p-3 flex flex-col gap-1">'
      +   '<span class="text-xs text-sky-100/60">Net Irrigation</span>'
      +   '<span class="text-lg font-medium text-white">' + (isFinite(netMm) ? netMm.toFixed(1) + " mm" : "—") + '</span>'
      +   '<span class="text-[10px] text-sky-100/50">' + (isFinite(netL) ? netL.toFixed(1) + " L/m²" : "") + '</span>'
      + '</div>'
      + '<div class="cmd-card rounded-xl p-3 flex flex-col gap-1">'
      +   '<span class="text-xs text-sky-100/60">💡 Tip</span>'
      +   '<span class="text-xs text-sky-100/80 leading-snug">' + (tip || "No tip available") + '</span>'
      + '</div>';
  }

  btn.addEventListener("click", function () {
    var city = document.getElementById("ag-city").value;
    btn.disabled = true;
    var label = btn.querySelector(".btn-label");
    if (label) { label.textContent = "Analyzing…"; }

    fetch("/api/agriculture?city=" + encodeURIComponent(city))
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (d.error) { return; }

        if (moistEl) { moistEl.textContent = d.soil_moisture_pct + "%"; setMoisturePct(d.soil_moisture_pct); }
        if (evapEl)  { evapEl.textContent  = Number(d.evapotranspiration_mm).toFixed(2) + " mm"; }
        if (et0El)   { et0El.textContent   = d.et0_method || "—"; }

        // Frost pill color
        if (frostEl) {
          frostEl.textContent = d.frost_risk || "—";
          frostEl.setAttribute("data-frost", d.frost_risk || "Low");
        }

        // Urgency pill
        if (urgency) {
          var u = d.irrigation_urgency || "low";
          urgency.textContent = u.charAt(0).toUpperCase() + u.slice(1);
          urgency.className = "ml-auto text-xs font-bold px-3 py-1 rounded-full " + urgencyClass(u);
        }

        if (advice) { advice.textContent = d.irrigation_advice || "No guidance available."; }
        setTips(d);
      })
      .catch(function () {})
      .finally(function () {
        btn.disabled = false;
        if (label) { label.textContent = "Analyze Soil"; }
      });
  });
})();
