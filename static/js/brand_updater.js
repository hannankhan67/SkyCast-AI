/* SkyCast - synchronize the visible brand with the current subscription. */
(function () {
  "use strict";

  function updateSiteBranding(plan) {
    var normalized = String(plan || "free").toLowerCase();
    var isPremium = normalized === "premium";
    var brand = document.getElementById("siteBrand");
    var body = document.body;
    var badge = document.getElementById("premium-brand-badge");

    if (body) {
      body.setAttribute("data-user-plan", normalized);
      body.setAttribute("data-is-premium", isPremium ? "true" : "false");
    }
    if (brand && isPremium && !badge) {
      badge = document.createElement("span");
      badge.id = "premium-brand-badge";
      badge.className = "inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-[9px] sm:text-[10px] font-bold tracking-widest uppercase whitespace-nowrap bg-amber-500/10 text-amber-300 border border-amber-500/30 shadow-[0_0_12px_rgba(245,158,11,0.25)]";
      badge.innerHTML = '<span aria-hidden="true">⭐</span> PREMIUM';
      brand.appendChild(badge);
    } else if (badge && !isPremium) {
      badge.remove();
    }

    if (isPremium) {
      document.title = document.title.replace(/SkyCast AI/g, "SkyCast Premium").replace(/^SkyCast(?! Premium)/, "SkyCast Premium");
    } else {
      document.title = document.title.replace(/SkyCast Premium/g, "SkyCast").replace(/SkyCast AI/g, "SkyCast");
    }
  }

  window.updateSiteBranding = updateSiteBranding;
  document.addEventListener("DOMContentLoaded", function () {
    var body = document.body;
    if (body && body.getAttribute("data-user-authenticated") === "true") {
      updateSiteBranding(body.getAttribute("data-user-plan") || "free");
    }
  });
}());