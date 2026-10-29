/* SkyCast AI — Solar Estimator */
(function () {
  "use strict";
  var btn = document.getElementById("solar-calc");
  if (!btn) return;

  function renderHourly(hours, peak) {
    var box = document.getElementById("s-hourly");
    if (!box) return;
    var max = peak || 1;
    box.innerHTML = hours.map(function (h) {
      var pct = Math.max(2, Math.round((h.output_kw / max) * 100));
      return '<div class="flex flex-col items-center justify-end h-full min-w-[2.2rem]" title="' +
        h.hour + " · " + h.output_kw + " kW · " + h.ghi_wm2 + ' W/m²">' +
        '<span class="text-[10px] text-sky-100/80 mb-1">' + h.output_kw + '</span>' +
        '<div class="w-5 rounded-t-lg bg-gradient-to-t from-amber-400/80 to-amber-200" style="height:' + pct + '%"></div>' +
        '<span class="text-[9px] text-sky-100/50 mt-1">' + h.hour.slice(0, 2) + '</span></div>';
    }).join("");
  }

  btn.addEventListener("click", function () {
    var city = document.getElementById("solar-city").value;
    var size = parseFloat(document.getElementById("solar-size").value) || 5;
    var eff = parseFloat(document.getElementById("solar-eff").value) || 0.18;
    fetch("/api/solar?city=" + encodeURIComponent(city) + "&size=" + size + "&eff=" + eff)
      .then(function (r) { return r.json(); })
      .then(function (d) {
        var psh = document.getElementById("s-psh"); if (psh) psh.textContent = d.peak_sun_hours + " h";
        var kwh = document.getElementById("s-kwh"); if (kwh) kwh.textContent = d.daily_kwh + " kWh";
        var co2 = document.getElementById("s-co2"); if (co2) co2.textContent = d.co2_saved_kg + " kg";
        var cl = document.getElementById("s-cloud"); if (cl) cl.textContent = d.cloud_cover_pct + "%";
        var pk = document.getElementById("s-peak"); if (pk) pk.textContent = d.peak_output_kw + " kW";
        var mo = document.getElementById("s-month"); if (mo) mo.textContent = d.monthly_kwh + " kWh";
        var cy = document.getElementById("s-co2y"); if (cy) cy.textContent = d.co2_saved_year_tons + " t";
        renderHourly(d.hourly_output || [], d.peak_output_kw);
      })
      .catch(function () {});
  });

  // Initial calculation on page load
  btn.click();
})();
