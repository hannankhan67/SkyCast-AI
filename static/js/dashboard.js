/* SkyCast AI — Dashboard page
   Loads the user's ACTUAL saved cities (from /api/user/saved-cities),
   renders weather cards for each, and powers the "Manage Cities" panel:
   pick a country, pick a city, add it; remove cities from cards or the list. */
(function () {
  "use strict";
  var $ = function (s) { return document.querySelector(s); };

  var grid = document.getElementById("city-grid");
  if (!grid) return;

  // time-aware greeting
  var h = new Date().getHours();
  var g = h < 12 ? "Morning" : h < 17 ? "Afternoon" : "Evening";
  var gp = document.getElementById("greeting-part");
  if (gp) gp.textContent = g;

  /* ---------- state ---------- */
  var saved = [];       // ordered list of saved city keys
  var catalog = [];     // [{ country, cities: [{ key, name }] }]
  var countryEl = $("#city-country");
  var pickerEl = $("#city-picker");
  var addBtn = $("#city-add");
  var addStatus = $("#add-status");
  var savedList = $("#saved-list");
  var savedCount = $("#saved-count");

  function countryOf(key) {
    for (var i = 0; i < catalog.length; i++) {
      for (var j = 0; j < catalog[i].cities.length; j++) {
        if (catalog[i].cities[j].key === key) return catalog[i].country;
      }
    }
    return "";
  }
  function cityName(key) {
    for (var i = 0; i < catalog.length; i++) {
      for (var j = 0; j < catalog[i].cities.length; j++) {
        if (catalog[i].cities[j].key === key) return catalog[i].cities[j].name;
      }
    }
    return key.charAt(0).toUpperCase() + key.slice(1);
  }

  /* ---------- weather cards ---------- */
  function card(key, w) {
    var name = cityName(key);
    var country = countryOf(key);
    return (
      '<div class="rounded-[2rem] bg-white/10 backdrop-blur-lg border border-white/20 p-7 shadow-[0_8px_32px_0_rgba(31,38,135,0.15)] group hover:bg-white/15 hover:-translate-y-1 transition-all duration-300 relative">' +
        '<button type="button" data-key="' + key + '" title="Remove ' + name + '" ' +
          'class="remove-city absolute top-3 right-3 w-7 h-7 rounded-full bg-white/10 hover:bg-rose-400/30 border border-white/20 text-sky-100/70 hover:text-white text-sm leading-none transition-all">×</button>' +
        '<a href="/weather?city=' + encodeURIComponent(key) + '" class="block">' +
          '<div class="flex items-start justify-between pr-8">' +
            '<div>' +
              '<p class="text-lg font-medium">' + name + "</p>" +
              '<p class="text-xs text-sky-100/60 mt-0.5">' + country + " · " + (w.condition || "") + "</p>" +
            "</div>" +
            '<img src="' + w.icon + '" alt="' + (w.condition || "") + '" class="w-12 h-12 object-contain group-hover:scale-110 transition-transform duration-300">' +
          "</div>" +
          '<p class="text-5xl font-light mt-4">' + w.temp + "°</p>" +
          '<div class="mt-5 flex justify-between text-xs text-sky-100/70 font-light">' +
            "<span>Humidity " + w.humidity + "%</span><span>Wind " + w.wind + " km/h</span>" +
          "</div>" +
        "</a>" +
      "</div>"
    );
  }

  function renderCards() {
    if (!grid) return;
    grid.innerHTML = "";
    if (!saved.length) {
      grid.innerHTML = '<p class="sm:col-span-2 rounded-[2rem] bg-white/5 border border-white/10 p-8 text-sky-100/60 text-sm">No saved cities yet — add one from the Manage Cities panel.</p>';
      return;
    }
    var pending = saved.length;
    saved.forEach(function (key) {
      fetch("/api/weather?city=" + encodeURIComponent(key))
        .then(function (r) { return r.json(); })
        .then(function (w) {
          if (!w || w.error) {
            pending--;
            if (pending <= 0) finishCardFooter();
            return;
          }
          grid.insertAdjacentHTML("beforeend", card(key, w));
          pending--;
          if (pending <= 0) finishCardFooter();
        })
        .catch(function () { pending--; if (pending <= 0) finishCardFooter(); });
    });
  }

  function finishCardFooter() {
    if (!saved.length) return;
    var note = document.getElementById("city-sync-note");
    if (!note) {
      note = document.createElement("p");
      note.id = "city-sync-note";
      note.className = "sm:col-span-2 text-sm text-sky-100/50 font-light";
      grid.appendChild(note);
    }
    note.textContent = saved.length + (saved.length === 1 ? " city" : " cities") + " synced from your saved list.";
  }

  /* ---------- Manage Cities panel ---------- */
  function refreshSavedList() {
    if (!savedList) return;
    if (!saved.length) {
      savedList.innerHTML = '<p class="text-xs text-sky-100/60">Your list is empty.</p>';
      if (savedCount) savedCount.textContent = "0 saved";
      return;
    }
    savedList.innerHTML = saved.map(function (key) {
      var name = cityName(key);
      var country = countryOf(key);
      return (
        '<div class="flex items-center justify-between rounded-xl bg-white/10 border border-white/15 px-3 py-2 text-sm">' +
          '<span class="text-sky-100/90 truncate">' + name +
            (country ? ' <span class="text-sky-100/45 font-light">· ' + country + "</span>" : "") +
          "</span>" +
          '<button type="button" data-key="' + key + '" title="Remove ' + name + '" class="remove-city shrink-0 ml-2 w-6 h-6 rounded-full bg-white/10 hover:bg-rose-400/30 border border-white/20 text-sky-100/70 hover:text-white text-xs leading-none transition-all">×</button>' +
        "</div>"
      );
    }).join("");
    if (savedCount) savedCount.textContent = saved.length + (saved.length === 1 ? " city" : " cities") + " saved";
  }

  function rebuildPicker() {
    if (!countryEl || !pickerEl || !addBtn) return;
    var country = countryEl.value;
    if (!country) {
      pickerEl.innerHTML = '<option value="">Select a country first</option>';
      addBtn.disabled = true;
      return;
    }
    var group = null;
    for (var i = 0; i < catalog.length; i++) {
      if (catalog[i].country === country) { group = catalog[i]; break; }
    }
    var options = (group ? group.cities : []).filter(function (c) {
      return saved.indexOf(c.key) === -1;
    });
    if (!options.length) {
      pickerEl.innerHTML = '<option value="">All cities in this country are added</option>';
      addBtn.disabled = true;
      return;
    }
    pickerEl.innerHTML = options.map(function (c) {
      return '<option value="' + c.key + '">' + c.name + "</option>";
    }).join("");
    addBtn.disabled = false;
  }

  function showStatus(msg, ok) {
    if (!addStatus) return;
    addStatus.textContent = msg;
    addStatus.className = "mt-3 text-xs font-medium " + (ok ? "text-emerald-300" : "text-rose-300");
  }

  function addCity(key) {
    if (!addBtn) return;
    addBtn.disabled = true;
    addBtn.textContent = "Adding…";
    fetch("/api/user/saved-cities", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ city: key }),
    })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        addBtn.textContent = "+ Add City";
        if (d && d.ok && Array.isArray(d.cities)) {
          saved = d.cities;
          refreshSavedList();
          rebuildPicker();
          renderCards();
          showStatus("✓ " + cityName(key) + " added to your list.", true);
        } else {
          addBtn.disabled = false;
          showStatus((d && d.error) || "Could not add city.", false);
        }
      })
      .catch(function () {
        addBtn.textContent = "+ Add City";
        addBtn.disabled = false;
        showStatus("Network error — please try again.", false);
      });
  }

  function removeCity(key) {
    fetch("/api/user/saved-cities/" + encodeURIComponent(key), { method: "DELETE" })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (d && d.ok && Array.isArray(d.cities)) {
          saved = d.cities;
          refreshSavedList();
          rebuildPicker();
          renderCards();
          showStatus("✓ " + cityName(key) + " removed.", true);
        } else {
          showStatus("Could not remove city.", false);
        }
      })
      .catch(function () { showStatus("Network error — please try again.", false); });
  }

  // delegate remove clicks (cards + list buttons)
  document.addEventListener("click", function (e) {
    var btn = e.target.closest ? e.target.closest(".remove-city") : null;
    if (!btn || !btn.getAttribute("data-key")) return;
    removeCity(btn.getAttribute("data-key"));
  });

  if (countryEl) countryEl.addEventListener("change", rebuildPicker);
  if (addBtn) {
    addBtn.addEventListener("click", function () {
      if (pickerEl && pickerEl.value) addCity(pickerEl.value);
    });
  }

  /* ---------- bootstrap ---------- */
  function loadCatalog() {
    return fetch("/api/cities")
      .then(function (r) { return r.json(); })
      .then(function (d) {
        catalog = (d && d.countries) || [];
        if (countryEl) {
          countryEl.innerHTML =
            '<option value="">Choose a country…</option>' +
            catalog.map(function (c) {
              return '<option value="' + c.country + '">' + c.country + "</option>";
            }).join("");
        }
        return catalog;
      })
      .catch(function () { catalog = []; });
  }

  function loadSaved() {
    return fetch("/api/user/saved-cities")
      .then(function (r) { return r.json(); })
      .then(function (d) {
        saved = (d && d.cities) || [];
        return saved;
      })
      .catch(function () { saved = []; });
  }

  Promise.all([loadCatalog(), loadSaved()]).then(function () {
    refreshSavedList();
    rebuildPicker();
    renderCards();
  });
})();