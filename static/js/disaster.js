/* SkyCast AI — Disaster Response page
   Loads hazard assessment, nearby shelters and emergency helplines,
   plus an interactive Leaflet shelter map with hazard-type filters. */
(function () {
  "use strict";
  var $ = function (s) { return document.querySelector(s); };
  var esc = function (s) { return String(s == null ? "" : s).replace(/</g, "&lt;").replace(/>/g, "&gt;"); };

  /* --- Leaflet shelter map ------------------------------------------------ */
  var map = null;
  var markerLayer = null;
  var currentShelters = [];
  var currentFilter = "all";
  var userPos = null;
  var KIND_META = {
    heat:   { label: "Heatwave Relief Center", color: "#f87171", icon: "🔥" },
    flood:  { label: "Flood Emergency Shelter", color: "#60a5fa", icon: "🌊" },
    medical:{ label: "Medical Post", color: "#34d399", icon: "⛑️" },
  };

  function haversineKm(lat1, lon1, lat2, lon2) {
    var R = 6371, p1 = lat1 * Math.PI / 180, p2 = lat2 * Math.PI / 180;
    var dp = (lat2 - lat1) * Math.PI / 180, dl = (lon2 - lon1) * Math.PI / 180;
    var a = Math.sin(dp / 2) ** 2 + Math.cos(p1) * Math.cos(p2) * Math.sin(dl / 2) ** 2;
    return 2 * R * Math.asin(Math.sqrt(a));
  }

  function shelterDistance(s) {
    if (userPos) return haversineKm(userPos.lat, userPos.lon, s.lat, s.lon);
    return s.distance_km;
  }

  function directionsUrl(s) {
    var base = "https://www.google.com/maps/dir/?api=1&destination=" + s.lat + "," + s.lon;
    if (userPos) base += "&origin=" + userPos.lat + "," + userPos.lon;
    return base;
  }

  function ensureMap(lat, lon) {
    if (map) { map.setView([lat, lon], 10); return; }
    map = L.map("shelter-map").setView([lat, lon], 10);
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 18,
      attribution: "&copy; OpenStreetMap contributors",
    }).addTo(map);
    markerLayer = L.layerGroup().addTo(map);
    document.querySelectorAll(".map-filter").forEach(function (btn) {
      btn.addEventListener("click", function () {
        document.querySelectorAll(".map-filter").forEach(function (b) { b.classList.remove("active"); });
        btn.classList.add("active");
        currentFilter = btn.getAttribute("data-filter");
        drawMarkers();
      });
    });
  }

  function drawMarkers() {
    if (!markerLayer) return;
    markerLayer.clearLayers();
    currentShelters.forEach(function (s) {
      if (currentFilter !== "all" && s.kind !== currentFilter) return;
      var meta = KIND_META[s.kind] || KIND_META.heat;
      var icon = L.divIcon({
        className: "",
        html: '<div style="background:' + meta.color + ';width:34px;height:34px;border-radius:50%;' +
              'display:flex;align-items:center;justify-content:center;font-size:16px;' +
              'box-shadow:0 2px 10px rgba(0,0,0,.5);border:2px solid rgba(255,255,255,.85)">' + meta.icon + "</div>",
        iconSize: [34, 34],
        iconAnchor: [17, 17],
      });
      L.marker([s.lat, s.lon], { icon: icon })
        .bindPopup(
          "<b>" + esc(s.name) + "</b><br>" + meta.label +
          "<br>👥 " + esc(s.capacity) + " · 📍 " + esc(shelterDistance(s).toFixed(1)) + " km · 24h" +
          "<br><a href='" + directionsUrl(s) + "' target='_blank' rel='noopener'>Get directions ↗</a>"
        )
        .addTo(markerLayer);
    });
  }

  /* --- Page rendering ------------------------------------------------------ */
  function levelBadge(level) {
    var map = {
      nominal: ["NOMINAL", "bg-emerald-400/20 border-emerald-300/40 text-emerald-200"],
      watch: ["WATCH", "bg-amber-400/20 border-amber-300/40 text-amber-200"],
      severe: ["SEVERE", "bg-rose-400/20 border-rose-300/40 text-rose-200"],
    };
    var m = map[level] || map.nominal;
    return '<span id="level-badge" class="inline-flex items-center rounded-full px-4 py-1.5 text-xs font-bold tracking-widest border ' + m[1] + '">' + m[0] + "</span>";
  }

  function render(d) {
    var badge = $("#level-badge");
    if (badge) badge.outerHTML = levelBadge(d.level);
    if ($("#hz-temp")) $("#hz-temp").textContent = d.temp + "°";
    if ($("#hz-wind")) $("#hz-wind").textContent = d.wind + " km/h";
    if ($("#hz-uv")) $("#hz-uv").textContent = d.uv;
    if ($("#hz-hum")) $("#hz-hum").textContent = d.humidity + "%";

    var sum = $("#disaster-summary");
    if (sum) {
      var parts = [d.city + " · " + d.condition.toLowerCase() + " · " + d.temp + "°"];
      if (d.hazards && d.hazards.length) parts = parts.concat(d.hazards);
      if (d.advisories && d.advisories.length) parts = parts.concat(d.advisories);
      sum.innerHTML = '<p class="font-semibold text-sky-200 mb-1">' + d.city + "</p>" +
        parts.map(function (p) { return "<p class='mb-1'>• " + esc(p) + "</p>"; }).join("");
    }

    var hmsg = $("#hazard-msg");
    if (hmsg) {
      if (d.level === "severe") hmsg.innerHTML = '<p class="text-rose-200">⚠️ Active hazards detected. Review the advisories and consider these shelters.</p>';
      else if (d.level === "watch") hmsg.innerHTML = '<p class="text-amber-200">Watch conditions — no severe hazard right now, but stay informed.</p>';
      else hmsg.innerHTML = '<p class="text-emerald-200">Conditions are nominal. No immediate severe-weather action needed.</p>';
    }

    var sList = $("#shelter-list");
    if (sList) {
      sList.innerHTML = (d.shelters || []).map(function (s) {
        var meta = KIND_META[s.kind] || KIND_META.heat;
        return (
          '<div class="shelter-card rounded-2xl bg-white/10 border border-white/15 p-5">' +
            '<p class="text-sm font-medium leading-snug">' + meta.icon + " " + esc(s.name) + "</p>" +
            '<p class="text-[10px] uppercase tracking-widest mt-1" style="color:' + meta.color + '">' + esc(meta.label) + "</p>" +
             '<div class="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-xs text-sky-100/70 font-light">' +
               "<span>📍 " + esc(shelterDistance(s).toFixed(1)) + " km" + (userPos ? " from you" : " away") + "</span>" +
               "<span>👥 " + esc(s.capacity) + "</span>" +
               "<span>🕐 24h</span>" +
             "</div>" +
             '<a href="' + directionsUrl(s) + '" target="_blank" rel="noopener" class="mt-3 inline-flex items-center gap-1 text-xs rounded-full bg-white/15 hover:bg-white/25 border border-white/30 px-3 py-1.5 transition-all">Get directions ↗</a>' +
             '<p class="mt-3 text-[10px] font-mono text-sky-100/50">' + esc(s.lat) + ", " + esc(s.lon) + "</p>" +
           "</div>"
        );
      }).join("");
      if (!(d.shelters || []).length) sList.innerHTML = '<p class="text-sky-100/60 text-sm md:col-span-2">No shelter data for this city.</p>';
    }

    /* Interactive shelter map */
    var mapBox = $("#shelter-map");
    if (mapBox && d.shelters && d.shelters.length) {
      currentShelters = d.shelters;
      ensureMap(d.shelters[0].lat, d.shelters[0].lon);
      drawMarkers();
      setTimeout(function () { if (map) map.invalidateSize(); }, 150);
    }

    var hList = $("#helpline-list");
    if (hList) {
      hList.innerHTML = (d.helplines || []).map(function (h) {
        return (
          '<a href="tel:' + esc(h.phone.replace(/\s+/g, "")) + '" class="flex items-center justify-between rounded-2xl bg-white/10 border border-white/15 px-5 py-4 hover:bg-white/20 transition-all">' +
            "<div><p class=\"text-sm font-medium\">" + esc(h.name) + "</p><p class=\"text-xs text-sky-100/60 font-light\">" + esc(h.kind) + "</p></div>" +
            '<span class="text-lg font-bold tracking-widest text-sky-200">' + esc(h.phone) + "</span>" +
          "</a>"
        );
      }).join("");
    }
  }

  function load() {
    var city = $("#disaster-city") ? $("#disaster-city").value : "karachi";
    fetch("/api/disaster?city=" + encodeURIComponent(city))
      .then(function (r) { return r.json(); })
      .then(render)
      .catch(function () {
        var sum = $("#disaster-summary");
        if (sum) sum.innerHTML = "<p>Could not load the hazard assessment.</p>";
      });
  }

  var btn = $("#disaster-load");
  if (btn) {
    btn.addEventListener("click", load);
    var sel = $("#disaster-city");
    if (sel) sel.addEventListener("change", load);
  }
  load();

  if (navigator.geolocation) {
    navigator.geolocation.getCurrentPosition(function (pos) {
      userPos = { lat: pos.coords.latitude, lon: pos.coords.longitude };
      load();  // re-render distances "from you" + directions origin
    }, function () {});
  }
})();

/* SkyCast AI — Safety Advisory & Helplines (dynamic) */
(function () {
  "use strict";

  // ── Helplines ──────────────────────────────────────────────
  function renderHelplines(d) {
    var hList = document.getElementById("helpline-list");
    if (!hList) return;
    var items = d.helplines || [];
    if (!items.length) { hList.innerHTML = '<p class="text-sky-100/60 text-sm md:col-span-2">No helplines available.</p>'; return; }
    hList.innerHTML = items.map(function (h) {
      return '<a href="tel:' + String(h.number).replace(/\s+/g, "") + '" class="flex items-center justify-between rounded-2xl bg-white/10 border border-white/15 px-5 py-4 hover:bg-white/20 transition-all">' +
        '<div><p class="text-sm font-medium">' + (h.name || "") + '</p><p class="text-xs text-sky-100/60 font-light">' + (h.type || "") + '</p></div>' +
        '<span class="text-lg font-bold tracking-widest text-sky-200">' + (h.number || "") + '</span>' +
        '</a>';
    }).join("");
  }

  fetch("/api/v1/safety/helplines").then(function (r) { return r.json(); }).then(renderHelplines).catch(function () {});

  // ── Safety Advisory ────────────────────────────────────────
  function renderAdvisory(d) {
    var adv = d.advisory || {};
    var title = document.getElementById("safety-title");
    if (title) title.textContent = adv.action_title || "—";
    var doList = document.getElementById("safety-do");
    if (doList) doList.innerHTML = (adv.do_list || []).map(function (i) { return '<li class="flex gap-2"><span class="text-emerald-300">✓</span><span>' + i + '</span></li>'; }).join("");
    var dontList = document.getElementById("safety-dont");
    if (dontList) dontList.innerHTML = (adv.dont_list || []).map(function (i) { return '<li class="flex gap-2"><span class="text-rose-300">✕</span><span>' + i + '</span></li>'; }).join("");
  }

  function loadAdvisory(condition) {
    fetch("/api/v1/safety/advisory?condition=" + encodeURIComponent(condition))
      .then(function (r) { return r.json(); })
      .then(renderAdvisory)
      .catch(function () {});
    document.querySelectorAll(".safety-proto-btn").forEach(function (b) {
      var active = b.getAttribute("data-condition") === condition;
      b.classList.toggle("bg-sky-500/20", active);
      b.classList.toggle("border-sky-400/40", active);
      b.classList.toggle("bg-white/10", !active);
      b.classList.toggle("border-white/25", !active);
    });
  }

  document.querySelectorAll(".safety-proto-btn").forEach(function (b) {
    b.addEventListener("click", function () { loadAdvisory(b.getAttribute("data-condition")); });
  });
  loadAdvisory("thunderstorm");
})();