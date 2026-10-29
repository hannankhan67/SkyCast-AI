/* SkyCast AI — Assistant page chat UI */
(function () {
  "use strict";
  var form = document.getElementById("assistant-form");
  var input = document.getElementById("assistant-input");
  var history = document.getElementById("chat-history");
  if (!form || !input || !history) return;

  function addBubble(html, cls) {
    var div = document.createElement("div");
    div.className = cls + " rounded-2xl p-4 text-sm text-sky-100/90 max-w-[85%]";
    div.innerHTML = html;
    history.appendChild(div);
    history.scrollTop = history.scrollHeight;
  }

  form.addEventListener("submit", function (e) {
    e.preventDefault();
    var q = input.value.trim();
    if (!q) return;
    addBubble("<p>" + q.replace(/</g, "&lt;") + "</p>", "chat-bubble-user ml-auto");
    input.value = "";
    fetch("/api/assistant", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: q }),
    })
    .then(function (r) { if (!r.ok) throw new Error("bad response"); return r.json(); })
    .then(function (data) {
      // intent-based reply (rain / drying / packing / stargazing / running)
      if (data.answer) {
        addBubble('<p class="font-semibold text-sky-200 mb-1">SkyCast</p><p>' + data.answer.replace(/</g, "&lt;") + "</p>", "chat-bubble-ai");
        return;
      }
      // outfit reply
      var items = (data.outfit || []).map(function (x) { return "<li>" + x.replace(/</g, "&lt;") + "</li>"; }).join("");
      var acts = (data.activities || []).map(function (x) { return "<li>" + x.replace(/</g, "&lt;") + "</li>"; }).join("");
      var html = '<p class="font-semibold text-sky-200 mb-1">Outfit for ' + (data.city || "").replace(/</g, "&lt;") + ' — ' + (data.day || "") + '</p>' +
        '<p class="mb-1"><span class="text-sky-200">Condition:</span> ' + (data.condition || "").replace(/</g, "&lt;") + ' · High ' + (data.max || "") + '° · Low ' + (data.min || "") + '°</p>' +
        '<p class="mb-1"><span class="text-sky-200">UV:</span> ' + (data.uv || "") + ' · <span class="text-sky-200">Wind:</span> ' + (data.wind || "") + ' km/h</p>' +
        '<p class="font-semibold text-sky-200 mt-2">Wear:</p><ul class="list-disc list-inside ml-2">' + items + '</ul>' +
        '<p class="font-semibold text-sky-200 mt-2">Activities:</p><ul class="list-disc list-inside ml-2">' + acts + '</ul>';
      if (data.precipitation_advice) html += '<p class="mt-2 text-amber-200">' + data.precipitation_advice.replace(/</g, "&lt;") + '</p>';
      addBubble(html, "chat-bubble-ai");
    })
    .catch(function () { addBubble("<p>Sorry, I couldn't reach the assistant right now.</p>", "chat-bubble-ai"); });
  });

  window.fillQuery = function (text) { input.value = text; form.dispatchEvent(new Event("submit")); };

  /* --- Trip Packing Generator panel --- */
  var packCity = document.getElementById("pack-city");
  var packDay = document.getElementById("pack-day");
  var packTrip = document.getElementById("pack-trip");
  var packBtn = document.getElementById("pack-btn");
  var packMeta = document.getElementById("pack-meta");
  var packList = document.getElementById("pack-list");
  var packNotes = document.getElementById("pack-notes");
  if (packBtn && packCity && packDay && packTrip) {
    function renderPack(d) {
      packMeta.innerHTML = '<span class="font-semibold text-white">' + (d.city || "").replace(/</g, "&lt;") +
        '</span> — ' + (d.day || "") + ' · ' + (d.condition || "").replace(/</g, "&lt;") +
        '<br>High ' + (d.max || "") + '\u00b0 / Low ' + (d.min || "") + '\u00b0 · Wind chill ~' +
        (d.wind_chill != null ? d.wind_chill : "?") + '\u00b0 · Rain ' + (d.precip_prob != null ? d.precip_prob : "?") + '% · UV ' + (d.uv || "") + '';
      packList.innerHTML = (d.packing || []).map(function (x) {
        return '<li class="px-3 py-1.5 rounded-full bg-white/10 border border-white/20 text-sm">' + x.replace(/</g, "&lt;") + '</li>';
      }).join("");
      packNotes.innerHTML = (d.notes || []).map(function (n) {
        return '<li class="flex gap-2"><span class="text-sky-300">\u2022</span><span>' + n.replace(/</g, "&lt;") + '</span></li>';
      }).join("");
    }
    packBtn.addEventListener("click", function () {
      packBtn.disabled = true; packBtn.textContent = "Generating...";
      fetch("/api/packing", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ city: packCity.value, day_offset: parseInt(packDay.value, 10) || 0, trip_type: packTrip.value }),
      })
      .then(function (r) { return r.json(); })
      .then(renderPack)
      .catch(function () { packNotes.innerHTML = '<li class="text-rose-200">Could not generate list.</li>'; })
      .finally(function () { packBtn.disabled = false; packBtn.textContent = "Generate list"; });
    });
  }
})();
