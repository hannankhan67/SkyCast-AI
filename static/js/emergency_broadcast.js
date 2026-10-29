/* SkyCast AI — Emergency Broadcast Siren (client side)
   Polls the public GET /api/alerts/active endpoint and renders
   active broadcast_alerts into #emergencyToastContainer as
   glassmorphic severity-styled toasts. Mounts on every page via
   templates/layout.html so geofenced/global broadcasts reach all users. */
(function () {
  "use strict";

  var POLL_INTERVAL_MS = 300000;           // 5 minutes
  var TOAST_TTL_MS = 20000;                // auto-dismiss after 20s
  var KEY = "skycast-seen-broadcasts";     // sessionStorage dedupe

  var container = null;

  function getContainer() {
    if (container && document.body.contains(container)) return container;
    container = document.getElementById("emergencyToastContainer");
    if (!container) {
      container = document.createElement("div");
      container.id = "emergencyToastContainer";
      container.className =
        "fixed bottom-6 right-6 z-50 flex flex-col gap-3 max-w-md w-full px-4 pointer-events-none";
      document.body.appendChild(container);
    }
    return container;
  }

  function seen() {
    try { return JSON.parse(sessionStorage.getItem(KEY) || "[]"); }
    catch (e) { return []; }
  }

  function mark(id) {
    var s = seen();
    if (s.indexOf(id) === -1) {
      s.push(id);
      try { sessionStorage.setItem(KEY, JSON.stringify(s.slice(-20))); } catch (e) { /* ignore */ }
    }
  }

  function esc(t) {
    var d = document.createElement("div");
    d.textContent = t == null ? "" : String(t);
    return d.innerHTML;
  }

  function severityStyle(severity) {
    var s = String(severity || "").toUpperCase();
    if (s === "CRITICAL" || s === "EXTREME") {
      return {
        wrap: "rounded-2xl border border-rose-300/50 bg-rose-600/35 backdrop-blur-xl shadow-2xl px-5 py-4 text-sm leading-relaxed pointer-events-auto",
        title: "font-semibold text-rose-50",
        body: "text-rose-100/90 font-light mt-1",
        icon: "🚨"
      };
    }
    if (s === "WARNING" || s === "HIGH") {
      return {
        wrap: "rounded-2xl border border-amber-300/40 bg-amber-500/25 backdrop-blur-xl shadow-2xl px-5 py-4 text-sm leading-relaxed pointer-events-auto",
        title: "font-semibold text-amber-50",
        body: "text-amber-100/90 font-light mt-1",
        icon: "⚠️"
      };
    }
    return {
      wrap: "rounded-2xl border border-sky-300/40 bg-sky-500/25 backdrop-blur-xl shadow-2xl px-5 py-4 text-sm leading-relaxed pointer-events-auto",
      title: "font-semibold text-sky-50",
      body: "text-sky-100/90 font-light mt-1",
      icon: "📢"
    };
  }

  function showToast(alert) {
    var stack = getContainer();
    var style = severityStyle(alert.severity);
    var city = alert.target_city && alert.target_city !== "All"
      ? " — " + alert.target_city.toUpperCase() : "";

    var el = document.createElement("div");
    el.setAttribute("role", "alert");
    el.className = style.wrap;
    el.innerHTML =
      '<div class="flex items-start gap-3">'
      + '<span class="text-lg">' + style.icon + '</span>'
      + '<div class="flex-1">'
      + '<p class="' + style.title + '">' + esc(alert.title) + esc(city) + '</p>'
      + '<p class="' + style.body + '">' + esc(alert.message) + '</p>'
      + '</div>'
      + '<button class="opacity-70 hover:opacity-100 ml-2" aria-label="Dismiss">✕</button>'
      + '</div>';

    el.querySelector("button").addEventListener("click", function () { el.remove(); });
    stack.appendChild(el);
    setTimeout(function () { el.remove(); }, TOAST_TTL_MS);
  }

  function poll() {
    fetch("/api/alerts/active")
      .then(function (r) { return r.ok ? r.json() : { alerts: [] }; })
      .then(function (d) {
        (d.alerts || []).forEach(function (a) {
          if (!a || a.id == null) return;
          var id = String(a.id);
          if (seen().indexOf(id) !== -1) return;
          mark(id);
          showToast(a);
        });
      })
      .catch(function () { /* silent — public endpoint may be briefly unavailable */ });
  }

  function initEmergencyBroadcast() {
    poll();
    setInterval(poll, POLL_INTERVAL_MS);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initEmergencyBroadcast);
  } else {
    initEmergencyBroadcast();
  }

  /* Expose for manual testing / dashboards */
  window.SkyCastEmergency = { poll: poll, show: showToast };
})();