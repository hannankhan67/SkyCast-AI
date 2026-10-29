(function () {
  "use strict";

  function escapeHtml(value) {
    var node = document.createElement("div");
    node.textContent = value == null ? "" : String(value);
    return node.innerHTML;
  }

  function setText(id, value) {
    var element = document.getElementById(id);
    if (element) element.textContent = value == null ? "--" : value;
  }

    function loadStats() {
    return fetch("/admin/api/stats")
      .then(function (response) {
        if (!response.ok || response.redirected || response.status === 302) {
          setText("stat-users", "—");
          setText("stat-keys", "—");
          setText("stat-requests", "—");
          setText("stat-alerts", "—");
          return null;
        }
        var ct = response.headers.get("content-type") || "";
        if (ct.indexOf("application/json") === -1) return null;
        return response.json();
      })
      .then(function (data) {
        if (!data) return;
        setText("stat-users", data.total_users);
        setText("stat-keys", data.active_api_keys);
        setText("stat-requests", data.requests_24h);
        setText("stat-alerts", data.active_alerts);
      });
  }

  var userPage = 1;
  var userPerPage = 10;
  var userSearch = "";
  var userPlan = "all";

  // Plan presentation. Premium gets the glowing amber treatment, free stays muted.
  var PAID_PLANS = ["premium"];

  function isPaidPlan(plan) {
    return PAID_PLANS.indexOf((plan || "free").toLowerCase()) !== -1;
  }

  function planBadge(plan) {
    plan = (plan || "free").toLowerCase();
    if (plan === "premium") {
      return '<span class="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-amber-500/10 text-amber-300 border border-amber-500/30 shadow-[0_0_10px_rgba(245,158,11,0.15)]">⭐ Premium</span>';
    }
    return '<span class="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-slate-800/80 text-slate-400 border border-slate-700/50">Free Tier</span>';
  }

  function planOptions(selected) {
    return [["free", "Plan: Free"], ["premium", "Plan: ⭐ Premium"]].map(function (pair) {
      return '<option value="' + pair[0] + '"' + (pair[0] === selected ? ' selected' : '') + '>'
        + pair[1] + '</option>';
    }).join("");
  }

  function paintTabs() {
    Array.prototype.forEach.call(document.querySelectorAll(".plan-tab"), function (tab) {
      var active = tab.dataset.plan === userPlan;
      tab.classList.toggle("bg-slate-800", active);
      tab.classList.toggle("text-white", active);
      tab.classList.toggle("text-amber-400", !active && tab.dataset.plan === "premium");
      tab.classList.toggle("hover:text-amber-300", !active && tab.dataset.plan === "premium");
      tab.classList.toggle("text-slate-400", !active && tab.dataset.plan !== "premium");
      tab.classList.toggle("hover:text-slate-200", !active && tab.dataset.plan !== "premium");
    });
  }

  function setFilter(plan) {
    userPlan = plan;
    userPage = 1;
    paintTabs();
    return loadUsers();
  }

  function renderUsers(data) {
    var tbody = document.getElementById("user-table");
    var users = data.users || [];
    var counts = data.counts || {};
    setText("count-all", counts.all == null ? 0 : counts.all);
    setText("count-premium", counts.premium == null ? 0 : counts.premium);
    setText("count-free", counts.free == null ? 0 : counts.free);
    paintTabs();
    if (!users.length) {
      tbody.innerHTML = '<tr><td colspan="5" class="py-8 text-center text-slate-500">No users found in this filter.</td></tr>';
      setText("user-count", "0 users");
      setText("users-page", "Page " + (data.page || 1));
      return;
    }
    tbody.innerHTML = users.map(function (user) {
      var plan = (user.plan || "free").toLowerCase();
      var paid = isPaidPlan(plan);
      var initials = escapeHtml((user.email || "?").substring(0, 2).toUpperCase());
      var rowBg = paid ? "bg-amber-500/[0.02] hover:bg-amber-500/[0.06]" : "hover:bg-slate-800/30";
      return '<tr class="border-b border-white/5 transition-colors ' + rowBg + '">'
        + '<td class="py-3 pr-3"><div class="flex items-center gap-3">'
        + '<div class="w-8 h-8 shrink-0 rounded-full flex items-center justify-center font-bold text-xs '
        + (paid ? "bg-amber-500/20 text-amber-300 border border-amber-500/30" : "bg-slate-800 text-slate-400")
        + '">' + initials + '</div><div><div class="font-medium text-slate-200 flex items-center gap-1.5">'
        + escapeHtml(user.email)
        + (plan === "premium" ? '<span class="text-amber-400 text-xs" title="Premium member">⭐</span>' : "")
        + '</div><div class="text-xs text-slate-500 font-mono">#' + escapeHtml(user.id) + " · " + escapeHtml(user.name || "User")
        + '</div></div></div></td>'
        + '<td class="py-3 pr-3">' + planBadge(plan) + '</td>'
        + '<td class="py-3 pr-3"><select data-user-id="' + escapeHtml(user.id) + '" class="role-select rounded-lg bg-slate-950 border border-white/15 px-2 py-1.5 text-xs">'
        + ['user', 'analyst', 'admin'].map(function (role) {
          return '<option value="' + role + '"' + (role === user.role ? ' selected' : '') + '>' + role + '</option>';
        }).join("")
        + '</select></td>'
        + '<td class="py-3 pr-3 text-xs text-slate-400 font-mono">' + escapeHtml(user.alerts || 0) + ' alerts · ' + escapeHtml(user.api_keys || 0) + ' keys</td>'
        + '<td class="py-3 text-right"><div class="flex items-center justify-end gap-2">'
        + '<select data-plan-id="' + escapeHtml(user.id) + '" class="plan-select rounded-lg bg-slate-950 border border-white/15 px-2 py-1.5 text-xs focus:outline-none focus:border-amber-500">'
        + planOptions(plan) + '</select>'
        + '<button data-delete-id="' + escapeHtml(user.id) + '" class="delete-user rounded-lg border border-rose-400/30 px-2.5 py-1.5 text-xs text-rose-300 hover:bg-rose-400/10">Delete</button>'
        + '</div></td></tr>';
    }).join("");
    setText("user-count", (data.total || 0) + " users");
    setText("users-page", "Page " + data.page);
    document.getElementById("users-prev").disabled = data.page <= 1;
    document.getElementById("users-next").disabled = data.page * data.per_page >= data.total;
    tbody.querySelectorAll(".role-select").forEach(function (select) {
      select.addEventListener("change", function () { updateRole(select.dataset.userId, select.value); });
    });
    tbody.querySelectorAll(".plan-select").forEach(function (select) {
      select.addEventListener("change", function () { updatePlan(select.dataset.planId, select.value); });
    });
    tbody.querySelectorAll(".delete-user").forEach(function (button) {
      button.addEventListener("click", function () { deleteUser(button.dataset.deleteId); });
    });
  }

    function loadUsers() {
    var params = new URLSearchParams({
      page: userPage, per_page: userPerPage, q: userSearch, plan: userPlan
    });
    return fetch("/admin/api/users-with-roles?" + params.toString())
      .then(function (response) {
        if (!response.ok || response.redirected || response.status === 302) {
          var tbody = document.getElementById("user-table");
          if (tbody) {
            tbody.innerHTML = '<tr><td colspan="5" class="py-6 text-center text-rose-400">Session expired. Please <a href="/login" class="underline">log in</a> again.</td></tr>';
          }
          return null;
        }
        var ct = response.headers.get("content-type") || "";
        if (ct.indexOf("application/json") === -1) return null;
        return response.json();
      })
      .then(function (data) {
        if (!data) return;
        renderUsers(data);
      });
  }

  function deleteUser(userId) {
    if (!window.confirm("Delete this user and all of their alerts, keys, tickets, and billing records?")) return;
    return fetch("/admin/api/users/" + encodeURIComponent(userId), { method: "DELETE" })
      .then(function (response) {
        return response.json().then(function (data) {
          if (!response.ok) throw new Error(data.error || "Delete failed");
          if (userPage > 1 && document.querySelectorAll("#user-table tr").length <= 1) userPage -= 1;
          return Promise.all([loadUsers(), loadStats()]);
        });
      }).catch(function (error) { window.alert(error.message); });
  }

  function updateRole(userId, role) {
    return fetch("/admin/api/users/" + encodeURIComponent(userId) + "/role", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ role: role })
    }).then(function (response) {
      return response.json().then(function (data) {
        if (!response.ok) throw new Error(data.error || "Role update failed");
        return loadUsers();
      });
    }).catch(function (error) { window.alert(error.message); loadUsers(); });
  }

  function flashStatus(message, ok) {
    var status = document.getElementById("user-status");
    if (!status) return;
    status.textContent = message;
    status.className = "mt-3 text-xs " + (ok ? "text-emerald-300" : "text-rose-300");
  }

  function updatePlan(userId, plan) {
    return fetch("/admin/api/users/" + encodeURIComponent(userId) + "/plan", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ plan: plan })
    }).then(function (response) {
      return response.json().then(function (data) {
        if (!response.ok) throw new Error(data.error || "Plan update failed");
        flashStatus(data.message || ("Plan updated to " + plan + "."), true);
        return Promise.all([loadUsers(), loadStats()]);
      });
    }).catch(function (error) {
      flashStatus(error.message, false);
      loadUsers();
    });
  }

  function publishBroadcast(event) {
    event.preventDefault();
    var button = document.getElementById("broadcast-button");
    var status = document.getElementById("broadcast-status");
    var body = {
      title: document.getElementById("alert-title").value.trim(),
      message: document.getElementById("alert-message").value.trim(),
      severity: document.getElementById("alert-severity").value,
      target_city: document.getElementById("alert-city").value.trim() || "All"
    };
    button.disabled = true;
    button.textContent = "Publishing...";
    fetch("/admin/api/admin/broadcast-alert", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body)
    }).then(function (response) {
      return response.json().then(function (data) {
        if (!response.ok || data.status === "error") throw new Error(data.message || "Broadcast failed");
        status.textContent = "Announcement published.";
        status.className = "text-sm text-emerald-300";
        document.getElementById("broadcast-form").reset();
        return loadStats();
      });
    }).catch(function (error) {
      status.textContent = error.message;
      status.className = "text-sm text-rose-300";
    }).finally(function () {
      button.disabled = false;
      button.textContent = "Publish announcement";
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    loadStats().catch(function () { setText("stat-health", "Unavailable"); });
    loadUsers().catch(function () {
      document.getElementById("user-table").innerHTML = '<tr><td colspan="5" class="py-6 text-center text-rose-300">Unable to load users.</td></tr>';
    });
    // Membership filter tabs (All / Premium / Free)
    Array.prototype.forEach.call(document.querySelectorAll(".plan-tab"), function (tab) {
      tab.addEventListener("click", function () { setFilter(tab.dataset.plan); });
    });
    paintTabs();
    document.getElementById("refresh-users").addEventListener("click", function () { loadUsers(); });
    document.getElementById("user-search").addEventListener("input", function (event) {
      userSearch = event.target.value.trim();
      userPage = 1;
      loadUsers();
    });
    document.getElementById("users-prev").addEventListener("click", function () { if (userPage > 1) { userPage -= 1; loadUsers(); } });
    document.getElementById("users-next").addEventListener("click", function () { userPage += 1; loadUsers(); });
    document.getElementById("broadcast-form").addEventListener("submit", publishBroadcast);
  });
}());
