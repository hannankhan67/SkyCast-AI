/* SkyCast AI — Health & Symptom Weather Index */
(function () {
  "use strict";
  var citySel = document.getElementById("health-city");
  var loadBtn = document.getElementById("health-load");
  if (!citySel || !loadBtn) return;

  function setCard(id, level, detail) {
    var card = document.getElementById(id);
    if (!card) return;
    var dot = card.querySelector(".rounded-full");
    var lvl = card.querySelector("[data-level]");
    var det = card.querySelector("[data-detail]");
    var cls = "low";
    if (level === "High") cls = "high";
    else if (level === "Moderate") cls = "moderate";
    card.classList.remove("lv-high", "lv-moderate", "lv-low");
    card.classList.add("lv-" + cls);
    if (dot) { dot.classList.remove("dot-high", "dot-moderate", "dot-low"); dot.classList.add("dot-" + cls); }
    if (lvl) lvl.textContent = level;
    if (det) det.textContent = detail;
  }

  function render(d) {
    setCard("card-migraine", d.migraine.level,
      "Pressure " + d.pressure + " hPa, " + (d.pressure_drop_hpa <= 0 ? d.pressure_drop_hpa : "+" + d.pressure_drop_hpa) +
      " hPa vs 3h ago. " + (d.migraine.level === "High" ? "Rapid drop — migraine trigger likely." :
      d.migraine.level === "Moderate" ? "Falling pressure — monitor symptoms." : "Stable pressure."));
    setCard("card-asthma", d.asthma.level,
      "AQI " + d.asthma.aqi + " · PM2.5 " + d.asthma.pm25 + " · PM10 " + d.asthma.pm10 + " µg/m³. " +
      (d.asthma.level === "High" ? "Limit outdoor exertion." : d.asthma.level === "Moderate" ? "Sensitive groups take care." : "Air is clear."));
    setCard("card-joint", d.joint_pain.level,
      "Humidity " + d.joint_pain.humidity + "%. " + (d.joint_pain.level === "High" ? "Damp, low-pressure air — joints may ache." :
      d.joint_pain.level === "Moderate" ? "Some pressure on joints." : "Comfortable."));
    setCard("card-uv", d.uv.level, "UV index " + d.uv.index + ". " + d.uv.advice);
    setCard("card-pollen", d.pollen.level, "Index " + d.pollen.index + "/10 · " + d.pollen.season + ".");
    setCard("card-pressure", d.overall, "Overall environmental risk for " + (d.city || "") + ".");

    var ov = document.getElementById("health-overall-lvl");
    if (ov) {
      ov.textContent = d.overall;
      var wrap = document.getElementById("health-overall");
      wrap.classList.remove("lv-high", "lv-moderate", "lv-low");
      wrap.classList.add("lv-" + (d.overall === "High" ? "high" : d.overall === "Moderate" ? "moderate" : "low"));
    }
  }

  function load() {
    loadBtn.disabled = true; loadBtn.textContent = "Analyzing...";
    fetch("/api/health?city=" + encodeURIComponent(citySel.value))
      .then(function (r) { return r.json(); })
      .then(render)
      .catch(function () { setCard("card-migraine", "Low", "Could not load weather data."); })
      .finally(function () { loadBtn.disabled = false; loadBtn.textContent = "Analyze Conditions"; });
  }

  loadBtn.addEventListener("click", load);
  load();
})();
