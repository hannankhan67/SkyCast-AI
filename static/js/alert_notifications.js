/* SkyCast AI — Real-time Alert Notifications
   Polls the alert evaluation endpoint periodically and fires
   native browser notifications + in-page toasts for triggered
   threshold alerts. Mount on any page for authenticated users. */
(function () {
    "use strict";
    var $ = function (s) { return document.querySelector(s); };
    var esc = function (s) { return String(s == null ? "" : s).replace(/</g, "&lt;").replace(/>/g, "&gt;"); };

    /* ---- Config ---- */
    var POLL_INTERVAL_MS = 120000;   // 2 minutes
    var SEEN_TTL_MS = 300000;         // dedupe window (5 min)

    /* ---- State ---- */
    var seenAlerts = {};   // alert_id -> timestamp of last notification
    var toastStack = null;

    function _now() { return Date.now(); }
    function _cleanupSeen() {
        var cutoff = _now() - SEEN_TTL_MS;
        Object.keys(seenAlerts).forEach(function (k) {
            if (seenAlerts[k] < cutoff) delete seenAlerts[k];
        });
    }

    /* ---- Browser-native notification ---- */
    function _fireBrowserNotification(title, body) {
        if ("Notification" in window && Notification.permission === "granted") {
            try {
                new Notification(title, { body: body, icon: "/static/icons/logo.svg" });
            } catch (e) { /* ignore */ }
        }
    }

    /* ---- In-page toast ---- */
    function _getStack() {
        if (!toastStack) {
            toastStack = document.createElement("div");
            toastStack.className = "fixed bottom-6 right-6 z-[90] flex flex-col gap-3 w-[22rem] max-w-[90vw]";
            document.body.appendChild(toastStack);
        }
        return toastStack;
    }

    function _showToast(alert, metric, value) {
        var stack = _getStack();
        var el = document.createElement("div");
        el.className = "rounded-2xl border border-rose-300/40 bg-rose-500/25 backdrop-blur-xl shadow-2xl px-5 py-4 text-sm leading-relaxed";
        var title = "SkyCast Alert: " + (alert.city || "?").toUpperCase();
        el.innerHTML =
            '<div class="flex items-start gap-3">'
          + '<span class="text-lg">🚨</span>'
          + '<div class="flex-1">'
            + '<p class="font-semibold text-rose-50">' + esc(title) + '</p>'
            + '<p class="text-rose-100/90 font-light mt-1">'
            + esc(metric) + " now " + esc(value)
            + " (threshold " + esc(alert.operator || "") + " " + esc(alert.threshold || "") + ")"
            + '</p></div>'
          + '<button class="text-rose-100/70 hover:text-white ml-2" aria-label="Dismiss">✕</button></div>';
        el.querySelector("button").addEventListener("click", function () { el.remove(); });
        stack.appendChild(el);
        setTimeout(function () { el.remove(); }, 15000);
    }

    /* ---- Poll for triggered alerts ---- */
    function _checkAlerts() {
        fetch("/api/alerts/test", { method: "POST" })
            .then(function (r) { return r.json(); })
            .then(function (data) {
                var fired = data.fired || [];
                _cleanupSeen();
                var now = _now();
                fired.forEach(function (f) {
                    var a = f.alert || {};
                    var key = a.id || (a.city + a.metric);
                    if (seenAlerts[key] && (now - seenAlerts[key]) < SEEN_TTL_MS) return;
                    seenAlerts[key] = now;

                    var metricLabel = a.metric || "metric";
                    var value = f.value != null ? f.value : "—";
                    _showToast(a, metricLabel, value);

                    /* Fire browser notification if browser channel is selected */
                    var channels = String(a.channels || "").split(",").map(function (c) { return c.trim(); });
                    if (channels.indexOf("browser") !== -1) {
                        _fireBrowserNotification(
                            "SkyCast Alert: " + (a.city || "Unknown"),
                            metricLabel + " " + (a.operator || "") + " " + (a.threshold || "") + " — currently " + value
                        );
                    }
                });
            })
            .catch(function () { /* silent fail — user may not be authenticated */ });
    }

    /* ---- Public API ---- */
    var pollTimer = null;

    function initAlertNotifications(pollMs) {
        if (pollMs) POLL_INTERVAL_MS = pollMs;
        _checkAlerts();
        if (pollTimer) clearInterval(pollTimer);
        pollTimer = setInterval(_checkAlerts, POLL_INTERVAL_MS);
    }

    function stopAlertNotifications() {
        if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
    }

    /* ---- Auto-init on page load for authenticated users ---- */
    if (typeof window !== "undefined") {
        document.addEventListener("DOMContentLoaded", function () {
            /* Only auto-start if we detect an authenticated user session.
               The layout template marks logged-in users via a data attribute. */
            var userMarker = document.body.getAttribute("data-user-authenticated");
            if (userMarker === "true") {
                initAlertNotifications();
            }
        });
    }

    /* Expose globally so dashboards can control the lifecycle */
    window.SkyCastNotifications = {
        init: initAlertNotifications,
        stop: stopAlertNotifications,
        test: _checkAlerts
    };
})();
