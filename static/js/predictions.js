/* SkyCast AI - AI Predictions Page */
(function () {
  "use strict";
  var citySelect = document.getElementById("pred-city");
  var loadBtn = document.getElementById("pred-load");
  if (!loadBtn) return;

  var EMOJI = {
    clear: "\u2600\ufe0f",
    partly: "\u26c5",
    cloud: "\u2601\ufe0f",
    drizzle: "\ud83c\udf26\ufe0f",
    rain: "\ud83c\udf27\ufe0f",
    storm: "\u26c8\ufe0f",
    fog: "\ud83c\udf2b\ufe0f",
    windy: "\ud83d\udca8",
    drip: "\ud83d\udca7",
    shirt: "\ud83d\udc55",
    umbrella: "\u2602\ufe0f",
    sun: "\ud83c\udf24\ufe0f",
    pants: "\ud83d\udc56",
    hat: "\ud83e\udde2",
    shoe: "\ud83d\udc5f",
    glove: "\ud83e\udde4",
    scarf: "\ud83e\udde3",
    glasses: "\ud83d\udd76\ufe0f",
    route: "\ud83d\udee3\ufe0f",
    clock: "\ud83d\udd54",
    pin: "\ud83d\udccd",
    phone: "\ud83d\udcde",
    ok: "\u2705",
    warn: "\u26a0\ufe0f",
    bolt: "\u26a1"
  };

  function esc(t) {
    var d = document.createElement("div");
    d.textContent = t == null ? "" : String(t);
    return d.innerHTML;
  }

  function conditionClass(c) {
    c = (c || "").toLowerCase();
    if (c.indexOf("rain") !== -1 || c.indexOf("drizzle") !== -1 || c.indexOf("storm") !== -1) return "rain-alert";
    if (c.indexOf("cloud") !== -1 || c.indexOf("overcast") !== -1) return "caution";
    return "clear-sky";
  }

  function getEmoji(c) {
    c = (c || "").toLowerCase();
    if (c.indexOf("clear") !== -1) return EMOJI.clear;
    if (c.indexOf("partly") !== -1) return EMOJI.partly;
    if (c.indexOf("cloud") !== -1 || c.indexOf("overcast") !== -1) return EMOJI.cloud;
    if (c.indexOf("drizzle") !== -1) return EMOJI.drizzle;
    if (c.indexOf("rain") !== -1) return EMOJI.rain;
    if (c.indexOf("storm") !== -1) return EMOJI.storm;
    if (c.indexOf("fog") !== -1) return EMOJI.fog;
    return EMOJI.sun;
  }
/* ============ Weekly Forecast ============ */
  function renderForecast(data) {
    var el = document.getElementById("weekly-forecast");
    if (!data || !data.forecast) { el.innerHTML = "<div class='col-span-full text-center text-sky-100/60 py-10'>No data.</div>"; return; }
    var h = "";
    for (var i = 0; i < data.forecast.length; i++) {
      var d = data.forecast[i];
      var cls = conditionClass(d.condition);
      var today = i === 0 ? " ring-2 ring-sky-300/50 shadow-lg" : "";
      var todayLbl = i === 0 ? " <span class='text-[9px] uppercase tracking-widest bg-sky-400/30 text-sky-100 px-1.5 py-0.5 rounded-full'>Today</span>" : "";
      h += "<div class='day-card rounded-2xl p-4 " + cls + today + "'><div class='text-center'>" +
        "<p class='text-sm font-bold text-sky-200'>" + esc(d.day) + todayLbl + "</p>" +
        "<p class='text-xs text-sky-100/60'>" + esc(d.date) + "</p>" +
        "<div class='text-3xl my-3'>" + getEmoji(d.condition) + "</div>" +
        "<p class='text-[11px] text-sky-100/80'>" + esc(d.condition) + "</p>" +
        "<p class='text-xl font-bold mt-2'>" + d.max_temp + "\u00b0 <span class='text-sm font-normal text-sky-100/60'>" + d.min_temp + "\u00b0</span></p>" +
        "<div class='flex items-center justify-center gap-2 mt-2 text-[11px] text-sky-100/60'>" +
          "<span>" + EMOJI.drip + " " + d.precip_prob + "%</span>" +
          "<span>" + EMOJI.windy + " " + d.wind + "</span>" +
        "</div>" +
        "<div class='mt-3 inline-block text-[10px] px-2 py-0.5 rounded-full bg-white/10 border border-white/15 text-sky-100/70'>AI " + d.confidence + "%</div>" +
        "</div></div>";
    }
    el.innerHTML = h;
  }

  /* ============ Umbrella Decision ============ */
  function renderUmbrella(rec, current) {
    var el = document.getElementById("umbrella-decision");
    var mEl = document.getElementById("umbrella-metrics");
    if (!rec) return;

    var needs = !!rec.umbrella_needed;
    var badgeCls = needs
      ? "bg-rose-500/25 border-rose-300/50 text-rose-100"
      : "bg-emerald-500/25 border-emerald-300/50 text-emerald-100";
    var ringCls = needs ? "ring-4 ring-rose-400/30" : "ring-4 ring-emerald-400/30";

    el.innerHTML =
      "<div class='rounded-2xl p-5 border " + (needs ? "rain-alert" : "clear-sky") + " " + ringCls + "'>" +
        "<div class='text-6xl mb-2'>" + (needs ? EMOJI.umbrella : EMOJI.sun) + "</div>" +
        "<span class='inline-block px-3 py-1 rounded-full text-xs font-bold tracking-widest border " + badgeCls + "'>" +
          (needs ? "YES \u2014 CARRY AN UMBRELLA" : "NO \u2014 UMBRELLA NOT NEEDED") +
        "</span>" +
        "<p class='mt-3 text-sm text-sky-100/85 leading-relaxed'>" + esc(rec.umbrella_reason) + "</p>" +
      "</div>";

    if (!mEl) return;
    var chips = "";
    if (current) {
      var chipsArr = [
        current.condition ? getEmoji(current.condition) + " " + esc(current.condition) : "",
        current.temp != null ? "\ud83c\udf21\ufe0f " + current.temp + "\u00b0C" : "",
        current.precip_prob != null ? EMOJI.drip + " " + current.precip_prob + "%" : "",
        current.wind != null ? EMOJI.windy + " " + current.wind + " km/h" : "",
        current.uv != null ? "\ud83d\udd25 UV " + current.uv : ""
      ];
      for (var i = 0; i < chipsArr.length; i++) {
        if (chipsArr[i]) chips += "<span class='text-[11px] px-2.5 py-1 rounded-full bg-white/10 border border-white/15 text-sky-100/80'>" + chipsArr[i] + "</span>";
      }
    }
    mEl.innerHTML = chips;
  }
/* ============ Clothing Recommendations ============ */
  function renderClothing(rec, current) {
    var el = document.getElementById("clothing-rec");
    var condEl = document.getElementById("clothing-conditions");
    if (!rec) return;

    if (condEl && current) {
      condEl.innerHTML = "<span class='text-[11px] uppercase tracking-widest text-sky-100/60'>Conditions:</span>" +
        "<span class='text-xs px-2.5 py-1 rounded-full bg-white/10 border border-white/15 text-sky-100/80'>" + getEmoji(current.condition) + " " + esc(current.condition) + "</span>" +
        (current.temp != null ? "<span class='text-xs px-2.5 py-1 rounded-full bg-amber-400/20 border border-amber-300/30 text-amber-100'>" + current.temp + "\u00b0C</span>" : "") +
        (current.wind != null ? "<span class='text-xs px-2.5 py-1 rounded-full bg-white/10 border border-white/15 text-sky-100/80'>" + EMOJI.windy + " " + current.wind + " km/h</span>" : "") +
        (current.uv != null ? "<span class='text-xs px-2.5 py-1 rounded-full bg-orange-400/20 border border-orange-300/30 text-orange-100'>UV " + current.uv + "</span>" : "");
    }

    var h = "";
    h += "<div class='mb-5'><p class='text-[11px] uppercase tracking-widest text-sky-100/60 mb-2.5 flex items-center gap-1.5'>" + EMOJI.shirt + " Recommended Outfit</p><div class='flex flex-col gap-2'>";
    for (var i = 0; i < rec.outfit.length; i++) {
      var icon = i === 0 ? EMOJI.shirt : EMOJI.pants;
      h += "<div class='flex items-center gap-3 rounded-xl bg-white/5 border border-white/10 px-3.5 py-2.5'>" +
        "<span class='text-lg shrink-0'>" + icon + "</span>" +
        "<span class='text-sm text-sky-100/90'>" + esc(rec.outfit[i]) + "</span></div>";
    }
    h += "</div></div>";

    if (rec.fabrics && rec.fabrics.length) {
      h += "<div class='mb-5'><p class='text-[11px] uppercase tracking-widest text-sky-100/60 mb-2'>Best Fabrics</p><div class='flex flex-wrap gap-2'>";
      for (var j = 0; j < rec.fabrics.length; j++) {
        h += "<span class='text-xs px-3 py-1.5 rounded-full bg-sky-400/15 text-sky-100 border border-sky-300/30'>" + esc(rec.fabrics[j]) + "</span>";
      }
      h += "</div></div>";
    }

    if (rec.accessories && rec.accessories.length) {
      h += "<div><p class='text-[11px] uppercase tracking-widest text-sky-100/60 mb-2.5'>Accessories</p><div class='flex flex-col gap-2'>";
      for (var k = 0; k < rec.accessories.length; k++) {
        var a = rec.accessories[k].toLowerCase();
        var aIcon = EMOJI.umbrella;
        if (a.indexOf("jacket") !== -1 || a.indexOf("raincoat") !== -1 || a.indexOf("shell") !== -1 || a.indexOf("sweater") !== -1) aIcon = "\ud83e\udde7";
        else if (a.indexOf("sunglass") !== -1) aIcon = EMOJI.glasses;
        else if (a.indexOf("hat") !== -1 || a.indexOf("beanie") !== -1) aIcon = EMOJI.hat;
        else if (a.indexOf("shoe") !== -1 || a.indexOf("boot") !== -1) aIcon = EMOJI.shoe;
        else if (a.indexOf("glove") !== -1) aIcon = EMOJI.glove;
        else if (a.indexOf("scarf") !== -1) aIcon = EMOJI.scarf;
        else if (a.indexOf("sunscreen") !== -1 || a.indexOf("spf") !== -1) aIcon = "\ud83e\uddf2";
        h += "<div class='flex items-center gap-3 rounded-xl bg-white/5 border border-white/10 px-3.5 py-2.5'>" +
          "<span class='text-base shrink-0'>" + aIcon + "</span>" +
          "<span class='text-sm text-sky-100/85'>" + esc(rec.accessories[k]) + "</span></div>";
      }
      h += "</div></div>";
    }

    el.innerHTML = h;
  }
/* ============ Safe Routes ============ */
  function renderRoutes(routes) {
    var el = document.getElementById("routes-section");
    if (!routes || !routes.length) { el.innerHTML = "<div class='col-span-full text-center text-sky-100/60 py-8'>No route data.</div>"; return; }
    var h = "";
    for (var i = 0; i < routes.length; i++) {
      var r = routes[i];
            var status = r.status === "caution" ? "caution" : r.status === "moderate" ? "moderate" : "clear";
      var stCls = status === "caution" ? "bg-rose-500/20 border-rose-300/40 text-rose-200" :
                  status === "moderate" ? "bg-amber-500/20 border-amber-300/40 text-amber-200" :
                  "bg-emerald-500/20 border-emerald-300/40 text-emerald-200";
      var barCls = status === "caution" ? "bg-rose-400" : status === "moderate" ? "bg-amber-400" : "bg-emerald-400";
      var icon = status === "caution" ? EMOJI.warn : status === "moderate" ? EMOJI.bolt : EMOJI.ok;
      h += "<div class='relative overflow-hidden rounded-2xl bg-white/10 border border-white/15 backdrop-blur-xl p-5 pl-6 shadow-[0_8px_32px_0_rgba(31,38,135,0.15)] hover:bg-white/15 transition-all'>" +
        "<span class='absolute left-0 top-0 bottom-0 w-1.5 " + barCls + "'></span>" +
        "<div class='flex items-center justify-between gap-4'>" +
          "<div class='flex items-start gap-3'>" +
            "<span class='text-2xl shrink-0 mt-0.5'>" + icon + "</span>" +
            "<div><p class='font-semibold text-sky-100'>" + esc(r.name) + "</p>" +
            "<p class='text-xs text-sky-100/60 mt-0.5'>" + EMOJI.route + " " + esc(r.description) + "</p></div>" +
          "</div>" +
          "<div class='text-right shrink-0'>" +
            "<p class='text-lg font-bold text-sky-100'>" + EMOJI.clock + " " + r.estimated_time_min + "</p>" +
            "<span class='inline-block mt-1 text-[10px] uppercase tracking-widest px-2 py-0.5 rounded-full border " + stCls + "'>" + esc(r.status) + "</span>" +
          "</div>" +
        "</div>" +
        "<p class='text-xs text-sky-100/70 mt-3 pt-3 border-t border-white/10'>" + esc(r.advisory) + "</p>" +
      "</div>";
    }
    el.innerHTML = h;
  }

  /* ============ Relief Camps + Helplines ============ */
  function renderRelief(camps, helplines) {
    var cc = document.getElementById("camps-list");
    var hc = document.getElementById("helplines-list");
    if (!camps || !camps.length) { cc.innerHTML = "<p class='text-sm text-sky-100/70'>No camps found.</p>"; }
    else {
      var h = "";
      for (var i = 0; i < camps.length; i++) {
        var c = camps[i];
        h += "<div class='flex items-center justify-between gap-3 rounded-xl bg-white/5 border border-white/10 p-3.5 hover:bg-white/10 transition-all'>" +
          "<div class='flex items-start gap-2.5'><span class='text-xl'>" + EMOJI.pin + "</span>" +
          "<div><p class='text-sm font-semibold text-sky-200'>" + esc(c.name) + "</p>" +
          "<p class='text-xs text-sky-100/60 mt-0.5'>" + esc(c.type) + " \u00b7 " + esc(c.capacity) + "</p></div></div>" +
          "<div class='text-right shrink-0'><p class='text-lg font-bold text-sky-200'>" + c.distance_km + " km</p>" +
          "<span class='inline-block mt-1 text-[10px] px-2 py-0.5 rounded-full bg-emerald-500/20 border border-emerald-300/40 text-emerald-200'>" + esc(c.status) + "</span></div>" +
        "</div>";
      }
      cc.innerHTML = h;
    }
    if (!helplines || !helplines.length) { hc.innerHTML = "<p class='text-sm text-sky-100/70'>No helplines.</p>"; }
    else {
      var hh = "";
      for (var j = 0; j < helplines.length; j++) {
        var hl = helplines[j];
        hh += "<a href='tel:" + esc(hl.number) + "' class='flex items-center justify-between gap-3 rounded-xl bg-white/5 border border-white/10 p-3.5 hover:bg-white/10 transition-all group'>" +
          "<p class='text-sm font-semibold text-sky-200 group-hover:text-white'>" + EMOJI.phone + " " + esc(hl.name) + "</p>" +
          "<p class='text-lg font-bold text-emerald-300'>" + esc(hl.number) + "</p></a>";
      }
      hc.innerHTML = hh;
    }
  }

  /* ============ Load all ============ */
  function loadAll() {
    var city = citySelect ? citySelect.value : "karachi";
    loadBtn.disabled = true;
    loadBtn.textContent = "Loading...";

    var pending = 0;
    function track() { pending++; }
    function done() { pending--; if (pending === 0) { loadBtn.disabled = false; loadBtn.textContent = "Load Predictions"; } }

    track();
    fetch("/api/predictions/weekly?city=" + encodeURIComponent(city))
      .then(function(r){return r.json()})
      .then(function(d){if(d.forecast)renderForecast(d.forecast)})
      .catch(function(){})
      .then(done);

    track();
    fetch("/api/predictions/outfit?city=" + encodeURIComponent(city))
      .then(function(r){return r.json()})
      .then(function(d){if(d.recommendation){renderUmbrella(d.recommendation, d.current);renderClothing(d.recommendation, d.current)}})
      .catch(function(){})
      .then(done);

    track();
    fetch("/api/predictions/routes?city=" + encodeURIComponent(city))
      .then(function(r){return r.json()})
      .then(function(d){if(d.routes)renderRoutes(d.routes)})
      .catch(function(){})
      .then(done);

    track();
    fetch("/api/predictions/relief?city=" + encodeURIComponent(city))
      .then(function(r){return r.json()})
      .then(function(d){if(d.camps)renderRelief(d.camps, d.helplines)})
      .catch(function(){})
      .then(done);
  }

  loadBtn.addEventListener("click", loadAll);
  loadAll();
})();
