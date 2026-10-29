/* SkyCast AI — User settings / preferences + subscription management */

(function () {
  "use strict";

  var unit = document.body.getAttribute("data-pref-unit") || "c";

  /* ---------------- Temperature unit toggle ---------------- */

  document.querySelectorAll(".unit-btn").forEach(function (btn) {
    btn.addEventListener("click", function () {
      unit = btn.getAttribute("data-unit");
      document.querySelectorAll(".unit-btn").forEach(function (b) {
        var on = b === btn;
        b.className = "unit-btn flex-1 rounded-2xl border px-5 py-3 text-sm transition-all " +
          (on ? "bg-sky-400/90 text-slate-900 font-semibold border-sky-300"
              : "bg-white/10 border-white/25 hover:bg-white/20");
      });
    });
  });

  /* ---------------- Save preferences ---------------- */

  var save = document.getElementById("pref-save");

  if (save) {
    save.addEventListener("click", function () {
      var status = document.getElementById("pref-status");
      save.disabled = true;

      fetch("/api/user/preferences", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          home_city: (document.getElementById("pref-home-city") || {}).value,
          unit: unit,
          notify_threshold: (document.getElementById("pref-threshold") || {}).value,
          phone: (document.getElementById("pref-phone") || {}).value,
        }),
      })
        .then(function (r) { return r.json(); })
        .then(function (d) {
          if (status) {
            status.textContent = d && d.ok ? "✓ Preferences saved." : "✖ " + (d.error || "Save failed");
            status.classList.toggle("text-emerald-300", !!(d && d.ok));
            status.classList.toggle("text-rose-300", !(d && d.ok));
            status.classList.remove("hidden");
          }
        })
        .catch(function () {})
        .finally(function () { save.disabled = false; });
    });
  }

  /* ---------------- Subscription cancellation ---------------- */

  var cancelBtn = document.getElementById("btn-cancel-subscription");
  if (!cancelBtn) return;

  /* Premium routes that must relock the instant membership is revoked. The
     server injects the authoritative list via data-premium-paths. */
  var FALLBACK_RESTRICTED = [
    "/solar", "/agriculture", "/historical",
    "/assistant", "/predictions", "/alerts", "/disaster",
  ];
  var DASHBOARD = document.body.getAttribute("data-dashboard-url") || "/dashboard";
  var LOCAL_REVOKE_KEY = "skycast-premium-revoked";

  function restrictedPaths() {
    var raw = document.body.getAttribute("data-premium-paths") || "";
    var list = raw.split(",").map(function (p) { return p.trim(); }).filter(Boolean);
    return list.length ? list : FALLBACK_RESTRICTED;
  }

  /* Mirrors SkyToast.isRestricted() so eviction still works without toast.js. */
  function restrictedMatch(path) {
    var p = String(path || "").split("?")[0].split("#")[0];
    if (p.length > 1 && p.charAt(p.length - 1) === "/") p = p.slice(0, -1);

    var list = restrictedPaths();
    for (var i = 0; i < list.length; i++) {
      if (p === list[i] || p.indexOf(list[i] + "/") === 0) return list[i];
    }
    return null;
  }

  /* Queue a notice that survives the redirect / reload that follows. */
  function cancelNotice(message, sticky) {
    if (window.SkyToast && window.SkyToast.notify) {
      window.SkyToast.notify({
        title: "Membership canceled",
        message: message,
        tone: "warning",
        icon: "",
        timeout: sticky ? 0 : 10000,
      });
    }
  }

  var confirmOverlay = null;
  var confirmBox = null;
  var confirmCancelBtn = null;
  var confirmKeepBtn = null;
  var confirmKeyHandler = null;
  var isCancelling = false;

  function showConfirmModal() {
    if (confirmOverlay) return;

    confirmOverlay = document.createElement("div");
    confirmOverlay.className = "fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center p-4 z-50";
    confirmOverlay.setAttribute("role", "dialog");
    confirmOverlay.setAttribute("aria-modal", "true");

    confirmBox = document.createElement("div");
    confirmBox.className = "bg-slate-900 border border-slate-800 p-6 rounded-xl max-w-md w-full space-y-4";
    confirmBox.innerHTML =
      '<h3 class="text-lg font-semibold text-white">Cancel Premium Membership?</h3>' +
      '<p class="text-sm text-slate-400 leading-relaxed">' +
      "Your Specialized and Insights pages are locked the moment you confirm. You will " +
      "lose Solar ROI, Agri-Climate, Historical Data, AI Assistant, AI Predictions, " +
      "Active Alerts and Disaster Safety, and your account drops to Free immediately.</p>";

    confirmOverlay.appendChild(confirmBox);

    confirmCancelBtn = document.createElement("button");
    confirmCancelBtn.type = "button";
    confirmCancelBtn.className =
      "w-full rounded-full bg-rose-500 text-slate-950 font-semibold hover:bg-rose-400 " +
      "transition-all px-6 py-3 text-sm";
    confirmCancelBtn.textContent = "Yes, cancel membership";
    confirmBox.appendChild(confirmCancelBtn);

    confirmKeepBtn = document.createElement("button");
    confirmKeepBtn.type = "button";
    confirmKeepBtn.className =
      "w-full rounded-full border border-white/25 bg-white/10 font-medium " +
      "hover:bg-white/20 transition-all px-6 py-3 text-sm mt-3";
    confirmKeepBtn.textContent = "Keep membership";
    confirmBox.appendChild(confirmKeepBtn);

    /* Hoisted so the listener can actually be removed when the modal closes. */
    confirmKeyHandler = function (e) {
      if (e.key === "Escape") hideConfirmModal();
    };
    document.addEventListener("keydown", confirmKeyHandler);

    confirmCancelBtn.addEventListener("click", function () {
      if (isCancelling) return;
      isCancelling = true;
      confirmCancelBtn.disabled = true;
      confirmCancelBtn.textContent = "Cancelling…";

      fetch("/api/user/subscription/cancel", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
      })
        .then(function (r) { return r.json(); })
        .then(function (d) {
          if (d && d.ok) {
            hideConfirmModal();

            cancelBtn.textContent = "Membership Cancelled";
            cancelBtn.disabled = true;
            cancelBtn.className =
              "w-full rounded-full bg-slate-800/60 text-slate-500 border border-slate-700/50 " +
              "font-medium px-6 py-3 text-sm cursor-not-allowed";

            /* Broadcast the revocation so other tabs evict instantly too. */
            if (window.SkyToast && window.SkyToast.revoke) {
              window.SkyToast.revoke(d.restricted_paths);
            } else {
              try {
                window.localStorage.setItem(
                  LOCAL_REVOKE_KEY,
                  JSON.stringify({ at: Date.now(), paths: d.restricted_paths || [] })
                );
              } catch (err) { /* storage unavailable — ignore */ }
            }

            var message = d.message ||
              "Your membership has been canceled. Premium pages are now locked.";
            var lockedHere = restrictedMatch(window.location.pathname);

            if (d.evicted_from || lockedHere) {
              /* Cancelled while on a Premium route -> evict to the dashboard. */
              cancelNotice(message, true);
              window.location.replace(d.redirect || DASHBOARD);
              return;
            }

            /* Cancelled from Settings: relock the DOM in place — the navbar
               loses Specialized / Insights and the plan card flips to Free
               with no page refresh at all. */
            cancelNotice(message, false);
            if (window.updateSiteBranding) window.updateSiteBranding("free");
            if (window.SkyToast && window.SkyToast.relock) {
              window.SkyToast.relock();
            } else {
              /* Fallback for browsers where toast.js failed to load. */
              window.setTimeout(function () { window.location.reload(); }, 600);
            }
          } else {
            isCancelling = false;
            confirmCancelBtn.disabled = false;
            confirmCancelBtn.textContent = "Yes, cancel membership";

            var msg = document.createElement("p");
            msg.className = "text-sm text-rose-300";
            msg.textContent = d && d.error ? d.error : "Cancellation failed. Please try again.";
            confirmBox.insertBefore(msg, confirmCancelBtn);
          }
        })
        .catch(function () {
          isCancelling = false;
          confirmCancelBtn.disabled = false;
          confirmCancelBtn.textContent = "Yes, cancel membership";

          var msg = document.createElement("p");
          msg.className = "text-sm text-rose-300";
          msg.textContent = "Network error. Please try again.";
          confirmBox.insertBefore(msg, confirmCancelBtn);
        });
    });

    confirmKeepBtn.addEventListener("click", hideConfirmModal);

    confirmOverlay.addEventListener("click", function (e) {
      if (e.target === confirmOverlay) hideConfirmModal();
    });

    document.body.appendChild(confirmOverlay);
  }

  function hideConfirmModal() {
    if (confirmKeyHandler) {
      document.removeEventListener("keydown", confirmKeyHandler);
      confirmKeyHandler = null;
    }
    if (confirmOverlay && confirmOverlay.parentNode) {
      confirmOverlay.parentNode.removeChild(confirmOverlay);
    }
    confirmOverlay = null;
    confirmBox = null;
    confirmCancelBtn = null;
    confirmKeepBtn = null;
    isCancelling = false;
  }

  cancelBtn.addEventListener("click", showConfirmModal);
})();