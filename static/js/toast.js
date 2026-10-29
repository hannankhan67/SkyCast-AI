/* SkyCast AI — Glassmorphic toast notifications + instant Premium route eviction
 *
 * Public API (window.SkyToast):
 *   SkyToast.show({ title, message, tone, icon, timeout, action })
 *   SkyToast.notify(opts)         queue a notice that survives a redirect
 *   SkyToast.revoke(paths)        broadcast a Premium revocation to all tabs
 *   SkyToast.isRestricted(path)   matched Premium prefix, or null
 *   SkyToast.relock()             unmount Premium markup in place (no reload)
 *   SkyToast.evict()              bounce onto /dashboard if the route is locked
 *   SkyToast.clear()              dismiss every visible toast
 *
 * Premium revocation flow
 * -----------------------
 * The server downgrades the account and re-renders the navbar without the
 * Specialized / Insights dropdowns. This script adds the client half:
 *   1. a revoked membership is broadcast to every open tab;
 *   2. any tab sitting on a Premium URL is evicted to /dashboard at once;
 *   3. the cancellation notice rides along in sessionStorage, so it is still
 *      on screen after the redirect.
 */
(function () {
  "use strict";

  var DASHBOARD_FALLBACK = "/dashboard";

  /* Mirrors routes/auth.PREMIUM_PAGE_PREFIXES — the server injects the
     authoritative list through data-premium-paths on <body>. */
  var FALLBACK_RESTRICTED = [
    "/solar", "/agriculture", "/historical",
    "/assistant", "/predictions", "/alerts", "/disaster",
  ];

  var QUEUE_KEY = "skycast-toast-queue";
  var REVOKE_KEY = "skycast-premium-revoked";
  var CHANNEL_NAME = "skycast-premium";
  var QUEUE_TTL_MS = 20000;
  var PURGE_DELAY_MS = 2500;      /* no navigation happened -> drop queued copy */
  var DEFAULT_TIMEOUT_MS = 8000;

  var TONES = {
    success: {
      frame: "border-emerald-300/40 bg-emerald-500/20",
      title: "text-emerald-50", body: "text-emerald-100/90",
      bar: "bg-emerald-300/80", glyph: "✓",
    },
    danger: {
      frame: "border-rose-300/40 bg-rose-500/25",
      title: "text-rose-50", body: "text-rose-100/90",
      bar: "bg-rose-300/80", glyph: "✕",
    },
    warning: {
      frame: "border-amber-300/40 bg-amber-400/20",
      title: "text-amber-50", body: "text-amber-100/90",
      bar: "bg-amber-300/80", glyph: "\uD83D\uDD12",
    },
    info: {
      frame: "border-sky-300/40 bg-sky-500/20",
      title: "text-sky-50", body: "text-sky-100/90",
      bar: "bg-sky-300/80", glyph: "ⓘ",
    },
  };

  var ALIASES = { error: "danger", warn: "warning", message: "info", notice: "info" };

  function tone(key) {
    var name = ALIASES[String(key || "").toLowerCase()] || String(key || "").toLowerCase();
    return TONES[name] || TONES.info;
  }

  function body() {
    return document.body || document.documentElement;
  }

  function attr(name) {
    var el = document.body;
    return el ? el.getAttribute(name) : null;
  }

  function dashboardUrl() {
    return attr("data-dashboard-url") || DASHBOARD_FALLBACK;
  }

  function esc(value) {
    return String(value == null ? "" : value)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }

  function readJSON(storage, key, fallback) {
    try {
      var raw = storage.getItem(key);
      if (!raw) return fallback;
      var parsed = JSON.parse(raw);
      return parsed == null ? fallback : parsed;
    } catch (err) {
      return fallback;
    }
  }

  function writeJSON(storage, key, value) {
    try { storage.setItem(key, JSON.stringify(value)); } catch (err) { /* ignore */ }
  }

  /* ---------------- Self-contained animations ---------------- */

  var STYLE_ID = "sky-toast-styles";
  var STYLES = [
    "@keyframes sky-toast-in{from{opacity:0;transform:translateX(18px) scale(.97)}" +
      "to{opacity:1;transform:translateX(0) scale(1)}}",
    "@keyframes sky-toast-bar{from{transform:scaleX(1)}to{transform:scaleX(0)}}",
    ".sky-toast{animation:sky-toast-in .32s cubic-bezier(.22,1,.36,1) both}",
    ".sky-toast-out{opacity:0;transform:translateX(18px) scale(.97);" +
      "transition:opacity .24s ease,transform .24s ease}",
    ".sky-toast-bar{transform-origin:left center;animation:sky-toast-bar linear both}",
    "@media (prefers-reduced-motion: reduce){" +
      ".sky-toast{animation:none}.sky-toast-out{transition:none}.sky-toast-bar{animation:none}}",
  ].join("");

  function injectStyles() {
    if (document.getElementById(STYLE_ID) || !document.head) return;
    var style = document.createElement("style");
    style.id = STYLE_ID;
    style.textContent = STYLES;
    document.head.appendChild(style);
  }

  /* ---------------- Toast stack ---------------- */

  var stack = null;

  function getStack() {
    if (stack && stack.parentNode) return stack;
    stack = document.getElementById("sky-toasts");
    if (!stack) {
      stack = document.createElement("div");
      stack.id = "sky-toasts";
      stack.setAttribute("role", "status");
      stack.setAttribute("aria-live", "polite");
      /* Anchored top-right, just under the fixed navbar. */
      stack.className = "fixed top-24 right-4 sm:right-6 z-[95] flex flex-col gap-3 " +
        "w-[22rem] max-w-[92vw] pointer-events-none";
      var host = document.body;
      if (host) host.appendChild(stack);
    }
    return stack;
  }

  /* ---------------- Rendering ---------------- */

  function dismiss(el) {
    if (!el || !el.parentNode) return;
    el.classList.add("sky-toast-out");
    window.setTimeout(function () {
      if (el.parentNode) el.parentNode.removeChild(el);
    }, 260);
  }

  function show(opts) {
    var config = opts || {};
    if (!config.message && !config.title) return null;
    var theme = tone(config.tone);
    var glyph = config.icon || theme.glyph;
    var timeout = config.timeout == null ? DEFAULT_TIMEOUT_MS : Number(config.timeout);
    if (isNaN(timeout)) timeout = DEFAULT_TIMEOUT_MS;

    injectStyles();
    var container = getStack();
    if (!container) return null;

    var el = document.createElement("div");
    el.className = "sky-toast pointer-events-auto rounded-2xl border backdrop-blur-xl " +
      "shadow-[0_18px_50px_-12px_rgba(0,0,0,0.55)] px-5 py-4 text-sm leading-relaxed " +
      theme.frame;

    var html = '<div class="flex items-start gap-3">';
    if (glyph) html += '<span class="text-lg leading-none mt-0.5">' + esc(glyph) + "</span>";
    html += '<div class="flex-1 min-w-0">';
    if (config.title) {
      html += '<p class="font-semibold ' + theme.title + '">' + esc(config.title) + "</p>";
    }
    if (config.message) {
      html += '<p class="' + theme.body + ' font-light ' +
        (config.title ? "mt-1 " : "") + '">' + esc(config.message) + "</p>";
    }
    if (config.action && config.action.href && config.action.label) {
      html += '<a href="' + esc(config.action.href) + '" class="mt-3 inline-flex items-center ' +
        "gap-1 rounded-full border border-white/30 bg-white/10 px-4 py-1.5 text-xs " +
        'font-medium hover:bg-white/20 transition-all">' + esc(config.action.label) +
        '<span aria-hidden="true">→</span></a>';
    }
    html += "</div>" +
      '<button type="button" class="text-white/60 hover:text-white ml-2 shrink-0 ' +
      'transition-colors" aria-label="Dismiss notification">✕</button>';
    if (timeout > 0) {
      html += '<span class="absolute inset-x-0 bottom-0 h-0.5 overflow-hidden rounded-b-2xl">' +
        '<span class="sky-toast-bar block h-full ' + theme.bar +
        '" style="animation-duration:' + timeout + 'ms"></span></span>';
    }
    html += "</div>";

    if (timeout > 0) el.className += " relative overflow-hidden";
    el.innerHTML = html;

    var closeBtn = el.querySelector("button");
    if (closeBtn) closeBtn.addEventListener("click", function () { dismiss(el); });

    container.appendChild(el);
    if (timeout > 0) {
      window.setTimeout(function () { dismiss(el); }, timeout);
    }
    return el;
  }

  function clear() {
    var container = document.getElementById("sky-toasts");
    if (!container) return;
    Array.prototype.slice.call(container.children).forEach(function (child) { dismiss(child); });
  }

  /* ---------------- Notices that survive a redirect ---------------- */

  var purgeTimer = null;

  function queueNotice(opts) {
    var list = readJSON(window.sessionStorage, QUEUE_KEY, []);
    if (!Array.isArray(list)) list = [];
    list.push({ at: Date.now(), opts: opts });
    writeJSON(window.sessionStorage, QUEUE_KEY, list.slice(-5));
  }

  function dropQueue() {
    try { window.sessionStorage.removeItem(QUEUE_KEY); } catch (err) { /* ignore */ }
  }

  function drainQueue() {
    var list = readJSON(window.sessionStorage, QUEUE_KEY, []);
    dropQueue();
    if (!Array.isArray(list)) return;
    var now = Date.now();
    list.forEach(function (entry) {
      if (!entry || !entry.opts || !entry.opts.message) return;
      if (now - (entry.at || 0) > QUEUE_TTL_MS) return;
      show(entry.opts);
    });
  }

  /* Show now AND stash a copy: if the page navigates (the cancellation
     redirect), the copy is drained on the next render. When nothing navigates
     within PURGE_DELAY_MS the copy is dropped so it never shows twice. */
  function notify(opts) {
    queueNotice(opts);
    var el = show(opts);
    if (purgeTimer) window.clearTimeout(purgeTimer);
    purgeTimer = window.setTimeout(dropQueue, PURGE_DELAY_MS);
    return el;
  }

  /* ---------------- Premium route locking / eviction ---------------- */

  var LOCK = "\uD83D\uDD12";   /* lock glyph */

  function restrictedPaths() {
    var raw = attr("data-premium-paths") || "";
    var list = raw.split(",").map(function (p) { return p.trim(); }).filter(Boolean);
    return list.length ? list : FALLBACK_RESTRICTED;
  }

  /* Segment-aware match: '/solar' and '/solar/' hit, '/solarium' never does. */
  function matchIn(list, path) {
    var clean = String(path == null ? window.location.pathname : path)
      .split("?")[0].split("#")[0];
    if (clean.length > 1 && clean.charAt(clean.length - 1) === "/") {
      clean = clean.slice(0, -1);
    }
    for (var i = 0; i < list.length; i++) {
      if (clean === list[i] || clean.indexOf(list[i] + "/") === 0) return list[i];
    }
    return null;
  }

  function isRestricted(path) {
    return matchIn(restrictedPaths(), path);
  }

  function isAuthenticated() {
    return attr("data-user-authenticated") === "true";
  }

  function isPremium() {
    return attr("data-is-premium") === "true";
  }

  /* ---------------- In-place DOM relock (no page refresh) ---------------- *
   * The next server render omits Specialized / Insights entirely, but a
   * cancellation must not wait for a navigation. Tagged Premium markup is
   * unmounted right here, so the navbar updates the moment the API confirms:
   *   [data-premium-only]   the element itself disappears
   *   [data-premium-group]  navbar dropdowns / dashboard tiles disappear
   *   [data-free-only]      the free-tier equivalent (upsell link, plan card)
   *                         is revealed in its place
   * Idempotent: a free account has no Premium markup left to remove.
   */
  function relock() {
    /* Announce the downgrade — evict() and settings.js read these back. */
    body().setAttribute("data-is-premium", "false");
    body().setAttribute("data-membership-cancelled", "true");

    var locked = 0;
    Array.prototype.forEach.call(
      document.querySelectorAll("[data-premium-only], [data-premium-group]"),
      function (node) {
        if (node.parentNode) node.parentNode.removeChild(node);
        locked++;
      }
    );

    var revealed = 0;
    Array.prototype.forEach.call(
      document.querySelectorAll("[data-free-only]"),
      function (node) {
        node.style.display = "";
        node.removeAttribute("hidden");
        revealed++;
      }
    );

    return { locked: locked, revealed: revealed };
  }

  /* Bounce a downgraded user off a locked route. Mirrors the server-side
     premium_required guard so direct URL entry can never stick. */
  function evict() {
    var locked = isRestricted(window.location.pathname);
    if (!locked || !isAuthenticated() || isPremium()) return false;

    var cancelled = attr("data-membership-cancelled") === "true";
    notify({
      title: cancelled ? "Membership canceled" : "Premium access locked",
      message: cancelled
        ? "Your membership has been canceled. " + locked +
          " is now locked \u2014 you were returned to your dashboard."
        : locked + " requires a Premium membership. You were returned to your dashboard.",
      tone: "warning",
      icon: LOCK,
    });
    window.location.replace(dashboardUrl());
    return true;
  }

  /* ---------------- Cross-tab revocation broadcast ---------------- */

  var channel = null;
  try {
    if (typeof window.BroadcastChannel === "function") {
      channel = new window.BroadcastChannel(CHANNEL_NAME);
    }
  } catch (err) { channel = null; }

  /* Used when another tab (or this one) reports the membership is gone.
     The body attributes may still be stale here, so the revocation payload
     is authoritative for the eviction decision. */
  function handleRevoke(payload) {
    /* Relock this tab's DOM first: the navbar drops Specialized / Insights
       immediately, whether or not it is sitting on a locked route. */
    relock();

    var paths = (payload && payload.paths && payload.paths.length)
      ? payload.paths
      : restrictedPaths();
    var locked = matchIn(paths, window.location.pathname);
    if (!locked) return false;

    notify({
      title: "Membership canceled",
      message: "Your membership has been canceled. " + locked +
        " is now locked \u2014 you were returned to your dashboard.",
      tone: "warning",
      icon: LOCK,
      timeout: 0,   /* sticky: the redirect is about to wipe the page anyway */
    });
    window.location.replace(dashboardUrl());
    return true;
  }

  /* Publish a revocation so every open tab relocks at once. */
  function revoke(paths) {
    var list = (paths && paths.length) ? paths : restrictedPaths();
    var payload = { at: Date.now(), paths: list };
    writeJSON(window.localStorage, REVOKE_KEY, payload);
    if (channel) {
      try { channel.postMessage(payload); } catch (err) { /* ignore */ }
    }
    return handleRevoke(payload);
  }

  if (channel) {
    channel.onmessage = function (event) { handleRevoke(event && event.data); };
  }

  window.addEventListener("storage", function (event) {
    if (!event || event.key !== REVOKE_KEY || !event.newValue) return;
    var payload = null;
    try { payload = JSON.parse(event.newValue); } catch (err) { return; }
    handleRevoke(payload);
  });

  /* ---------------- Public API + auto-init ---------------- */

  window.SkyToast = {
    show: show,
    notify: notify,
    clear: clear,
    revoke: revoke,
    relock: relock,
    evict: evict,
    isRestricted: isRestricted,
    restrictedPaths: restrictedPaths,
  };

  function init() {
    injectStyles();
    getStack();
    drainQueue();
    evict();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();