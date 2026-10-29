/* SkyCast AI — frontend glue
   Live weather fetch · time-aware greeting · 7-day forecast
   radar/terminal polish · big-data live tail
*/
(function () {
  "use strict";

  var $ = function (sel) { return document.querySelector(sel); };

  /* ---------- 1. Time-aware greeting ---------- */
  var hour = new Date().getHours();
  var greeting = hour < 12 ? "Good Morning" : hour < 17 ? "Good Afternoon" : "Good Evening";
  var greetingEl = $("#greeting");
  if (greetingEl) greetingEl.textContent = greeting;

  $("#year").textContent = String(new Date().getFullYear());

  /* ---------- 2. Live weather ---------- */
  var weatherIcon = $("#weather-icon");

  function uvLabel(v) {
    if (v < 3) return "Low";
    if (v < 6) return "Moderate";
    if (v < 8) return "High";
    if (v < 11) return "Very High";
    return "Extreme";
  }

  function renderForecast(list) {
    var grid = $("#forecast-grid");
    if (!grid) return;
    grid.innerHTML = list.map(function (d) {
      return (
        '<div class="rounded-3xl bg-white/10 backdrop-blur-lg border border-white/20 p-4 md:p-5 text-center transition-all duration-300 hover:bg-white/15 hover:-translate-y-1">' +
          '<p class="text-xs md:text-sm font-semibold tracking-widest uppercase text-sky-100">' + d.day + "</p>" +
          '<img src="' + d.icon + '" alt="' + d.condition + '" loading="lazy" class="w-12 h-12 md:w-14 md:h-14 mx-auto my-3 object-contain">' +
          '<p class="text-lg md:text-xl font-light">' +
            '<span class="font-semibold">' + d.max + "°</span>" +
            '<span class="text-sky-100/60 ml-1 text-sm">' + d.min + "°</span>" +
          "</p>" +
          '<p class="text-xs text-sky-100/70 mt-1 truncate">' + d.condition + "</p>" +
        "</div>"
      );
    }).join("");
  }

  function renderWeather(w) {
    $("#city-name").textContent = w.city;
    $("#temp").textContent = w.temp + "°";
    $("#condition").textContent = w.condition;
    $("#feels-like").textContent = w.feels_like + "°";
    $("#humidity").textContent = w.humidity + "%";
    $("#uv").innerHTML =
      w.uv + ' <span class="text-sm font-normal opacity-70 ml-1">' + uvLabel(w.uv) + "</span>";
    $("#wind").textContent = w.wind + " km/h";
    $("#pressure").textContent = w.pressure + " hPa";
    $("#visibility").textContent = w.visibility + " km";
    $("#sunrise").textContent = w.sunrise || "—";
    $("#sunset").textContent = w.sunset || "—";

    var cityShort = (w.city || "").split(",")[0];
    var sky = (w.condition || "").toLowerCase();
    sky = sky === "clear sky" ? "clear" : sky;
    $("#sky-line").textContent =
      "The sky is " + sky + " in " + cityShort + " today.";

    if (weatherIcon) weatherIcon.src = w.icon;

    var badge = $("#data-source");
    if (badge) {
      var live = w.live !== false;
      badge.textContent = live ? "LIVE" : "SIMULATED";
      badge.className =
        "inline-flex items-center space-x-1.5 rounded-full px-3 py-1 text-xs font-bold tracking-widest border " +
        (live
          ? "bg-emerald-400/20 border-emerald-300/40 text-emerald-200"
          : "bg-amber-400/20 border-amber-300/40 text-amber-200");
    }

    var upd = $("#update-time");
    if (upd) upd.textContent = (w.live !== false ? "Open-Meteo · " : w.source + " · ") + "Updated " + w.updated;

    renderForecast(w.forecast || []);
  }

  async function loadWeather(city) {
    try {
      var res = await fetch("/api/weather?city=" + encodeURIComponent(city));
      if (!res.ok) throw new Error("bad response");
      var w = await res.json();
      renderWeather(w);
    } catch (err) {
      console.error("Weather load failed:", err);
    }
  }

  var citySelect = $("#city-select");
  if (citySelect) {
    citySelect.addEventListener("change", function (e) {
      loadWeather(e.target.value);
    });
  }

  loadWeather("karachi");

  /* ---------- 3. Terminal "live tail" after the CSS cascade ---------- */
  var terminalTail = (function () {
    var cursor = $("#term-cursor");
    if (!cursor) return;

    var pool = [
      '<span class="text-yellow-400">[SYSTEM]</span> Heartbeat OK — datanode-03 (rack-1)',
      '<span class="text-cyan-400">[HDFS]</span> Replicating block bp-1024 → 2 datanodes',
      '<span class="text-purple-400">[ANALYTICS]</span> Anomaly flagged in record KHI-44812',
      '<span class="text-emerald-400">[FLASK]</span> /api/weather → 200 OK · 32ms',
      '<span class="text-cyan-400">[HDFS]</span> MapReduce job_20260829_0017 — 100% complete',
      '<span class="text-emerald-400">[OK]</span> Cluster healthy · 12/12 datanodes reporting',
    ];

    setTimeout(function () {
      var i = 0;
      setInterval(function () {
        var line = document.createElement("div");
        line.className = "log-live";
        line.innerHTML = pool[i % pool.length];
        cursor.parentNode.insertBefore(line, cursor);

        // keep the terminal tidy: drop oldest live lines
        while (cursor.parentNode.children.length > 11) {
          var first = cursor.parentNode.querySelector(".log-live");
          if (first && first !== cursor) first.remove();
          else break;
        }
        i += 1;
      }, 2600);
    }, 6500); // wait for the initial CSS cascade to finish
  })();
})();