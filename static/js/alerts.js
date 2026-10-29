/* SkyCast AI — Smart Alerts page
   Create / revoke threshold alerts, test them against live weather, and hook
   into the native Web Notifications API for browser pushes. */
(function () {
  "use strict";
  var $ = function (s) { return document.querySelector(s); };
  var esc = function (s) { return String(s == null ? "" : s).replace(/</g, "&lt;").replace(/>/g, "&gt;"); };

  /* ---------- Native browser notifications ---------- */
  function notificationsSupported() { return "Notification" in window; }

  function enableNotifications(cb) {
    if (!notificationsSupported()) { cb("unsupported"); return; }
    if (window.initPushSubscription) {
      window.initPushSubscription().then(function (result) {
        cb(result.permission || "denied");
      });
      return;
    }
    if (Notification.permission === "granted") { cb("granted"); return; }
    Notification.requestPermission().then(function (perm) { cb(perm); });
  }

  function fireBrowserNotification(title, body) {
    if (notificationsSupported() && Notification.permission === "granted") {
      try {
        new Notification(title, { body: body, icon: "/static/icons/logo.svg" });
      } catch (e) { /* some browsers require a service worker; ignore */ }
    }
  }

  var permBtn = $("#alert-notify-perm");
  if (permBtn) {
    permBtn.addEventListener("click", function () {
      enableNotifications(function (perm) {
        var msg = $("#alert-form-msg");
        if (perm === "granted") { msg.textContent = "✅ Browser notifications enabled."; }
        else if (perm === "denied") { msg.textContent = "Notifications were blocked by the browser."; }
        else { msg.textContent = "Notifications are unsupported here or permission pending."; }
      });
    });
  }

  /* ---------- Load + render ---------- */
  function renderLog(entries) {
    var box = $("#notif-log");
    if (!box) return;
    if (!entries.length) {
      box.innerHTML = '<p class="text-sky-100/60 font-light">No deliveries yet. Create an alert and press <span class="text-amber-200">Test</span>.</p>';
      return;
    }
    box.innerHTML = entries.map(function (e) {
      var okClass = e.status === "sent" ? "text-emerald-300" : (e.status === "failed" ? "text-rose-300" : "text-amber-300");
      return (
        '<div class="rounded-2xl bg-white/10 border border-white/15 px-4 py-3">' +
          '<div class="flex items-center justify-between gap-2">' +
            '<span class="uppercase tracking-widest text-[10px] text-sky-200 font-semibold">' + esc(e.channel) + "</span>" +
            '<span class="text-xs ' + okClass + '">' + esc(e.status) + "</span>" +
          "</div>" +
          '<p class="text-xs text-sky-100/70 font-light mt-1">' + esc(e.detail || "") + "</p>" +
          '<p class="text-[10px] text-sky-100/40 font-mono mt-1">' + esc(e.sent_at || "") + "</p>" +
        "</div>"
      );
    }).join("");
  }

  function renderAlerts(alerts) {
    var box = $("#alert-list");
    var count = $("#alert-count");
    if (!box) return;
    if (!alerts.length) {
      box.innerHTML = '<p class="text-sky-100/60 text-sm">No alerts yet. Create your first threshold above.</p>';
      if (count) count.textContent = "0";
      return;
    }
    if (count) count.textContent = alerts.length;
    box.innerHTML = alerts.map(function (a) {
      var channels = String(a.channels || "").split(",").map(function (c) { return c.trim(); }).filter(Boolean)
        .map(function (c) { return esc(c); }).join(" · ");
      return (
        '<div class="flex items-center justify-between gap-4 rounded-2xl bg-white/10 border border-white/15 px-5 py-4">' +
          '<div>' +
            '<p class="text-sm font-medium">' + esc(a.city) + " — " + esc(a.metric) + " " + esc(a.operator) + " " + esc(a.threshold) + "</p>" +
            '<p class="text-xs text-sky-100/60 mt-1">channels: ' + channels + " · created " + esc(a.created_at) + "</p>" +
          "</div>" +
          '<button data-alert-id="' + a.id + '" class="text-xs text-rose-200 hover:text-rose-100 border border-rose-300/30 hover:border-rose-300/60 rounded-full px-3 py-1.5 transition-all shrink-0">Revoke</button>' +
        "</div>"
      );
    }).join("");
  }

  function loadAll() {
    fetch("/api/alerts")
      .then(function (r) { return r.json(); })
      .then(function (d) {
        renderAlerts(d.alerts || []);
        renderLog(d.notification_log || []);
      })
      .catch(function () {});
  }
/* ---------- Create ---------- */
  var createBtn = $("#alert-create");
  if (createBtn) {
    createBtn.addEventListener("click", function () {
      var channels = Array.prototype.slice.call(document.querySelectorAll(".alert-channel"))
        .filter(function (cb) { return cb.checked; })
        .map(function (cb) { return cb.value; });
      var payload = {
        city: $("#alert-city").value,
        metric: $("#alert-metric").value,
        operator: $("#alert-op").value,
        threshold: parseFloat($("#alert-threshold").value),
        channels: channels,
      };
      fetch("/api/alerts", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      })
        .then(function (r) { return r.json().then(function (d) { return { status: r.status, body: d }; }); })
        .then(function (res) {
          var msg = $("#alert-form-msg");
          if (res.status === 200 && res.body.ok) { msg.textContent = "✅ Alert saved."; loadAll(); }
          else { msg.textContent = "⚠️ " + (res.body.error || "Could not save alert."); }
        })
        .catch(function () {});
    });
  }

  /* ---------- Revoke ---------- */
  document.addEventListener("click", function (e) {
    var btn = e.target.closest("[data-alert-id]");
    if (!btn) return;
    fetch("/api/alerts/" + btn.getAttribute("data-alert-id"), { method: "DELETE" })
      .then(function () { loadAll(); })
      .catch(function () {});
  });

  /* ---------- Test against live weather ---------- */
  var testBtn = $("#alert-test");
  if (testBtn) {
    testBtn.addEventListener("click", function () {
      var msg = $("#alert-form-msg");
      msg.textContent = "⏳ Evaluating against live weather…";
      fetch("/api/alerts/test", { method: "POST" })
        .then(function (r) { return r.json(); })
        .then(function (d) {
          var fired = d.fired || [];
          if (!fired.length) { msg.textContent = "✅ No alerts matched current conditions."; return; }
          var lines = fired.map(function (f) {
            var a = f.alert || {};
            return a.city + ": " + a.metric + " now " + f.value + " (threshold " + a.operator + " " + a.threshold + ")";
          });
          msg.textContent = "🚨 " + lines.join(" · ");
          fired.forEach(function (f) {
            var a = f.alert || {};
            (f.results || []).forEach(function (r) {
              if (r.channel === "browser" && r.ok) {
                fireBrowserNotification(
                  "SkyCast Alert: " + a.city,
                  a.metric + " " + a.operator + " " + a.threshold + " — currently " + f.value
                );
              }
            });
          });
          loadAll();
        })
        .catch(function () { msg.textContent = "⚠️ Could not run the test."; });
    });
  }

  loadAll();
})();