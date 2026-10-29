/* SkyCast AI — Geofenced Emergency Siren Listener (client)
   Acquires the user's location (only when geolocation permission was
   already granted — no intrusive site-wide popup), POSTs it to
   POST /api/user/broadcasts/active, and renders affecting broadcasts
   into #emergencyToastContainer with severity-styled toasts.

   Hardening vs. first draft:
     - alert.title/message/severity are HTML-escaped before innerHTML (XSS)
     - position is acquired once and refreshed at most every 5 min, not
       re-acquired on every poll cycle (GPS/battery churn)
     - network polling pauses while the tab is hidden (visibilitychange)
     - polling starts only if geolocation permission is already 'granted';
       pages may opt in explicitly via SkyCastGeofence.start(true)          */
class GeofenceSirenListener {
  constructor(pollIntervalSeconds = 30) {
    this.pollInterval = pollIntervalSeconds * 1000;
    this.positionRefreshMs = 5 * 60 * 1000;
    this.seenAlertIds = new Set(
      JSON.parse(sessionStorage.getItem('seen_geofence_alerts') || '[]')
    );
    this.cachedPosition = null;
    this.lastPositionAt = 0;
  }

  init() {
    this.refreshPositionAndCheck();
    setInterval(() => this.checkCached(), this.pollInterval);

    document.addEventListener('visibilitychange', () => {
      if (document.visibilityState === 'visible') this.checkCached();
    });
  }

  /* Poll using the cached fix; re-acquire GPS only if stale. */
  checkCached() {
    if (document.visibilityState !== 'visible') return;
    const age = Date.now() - this.lastPositionAt;
    if (this.cachedPosition && age < this.positionRefreshMs) {
      this.fetchActiveBroadcasts(this.cachedPosition.latitude, this.cachedPosition.longitude);
    } else {
      this.refreshPositionAndCheck();
    }
  }

  refreshPositionAndCheck() {
    if (!navigator.geolocation) {
      console.warn('Geolocation is not supported by this browser.');
      return;
    }
    navigator.geolocation.getCurrentPosition(
      (position) => {
        this.cachedPosition = position.coords;
        this.lastPositionAt = Date.now();
        this.fetchActiveBroadcasts(position.coords.latitude, position.coords.longitude);
      },
      (error) => console.warn(`Geolocation access error (${error.code}): ${error.message}`),
      { enableHighAccuracy: true, timeout: 10000, maximumAge: 60000 }
    );
  }

  async fetchActiveBroadcasts(latitude, longitude) {
    try {
      const response = await fetch('/api/user/broadcasts/active', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ latitude, longitude })
      });
      if (!response.ok) return;

      const result = await response.json();
      if (result.status === 'success' && result.alerts.length > 0) {
        result.alerts.forEach((alert) => {
          if (!this.seenAlertIds.has(alert.id)) {
            this.renderEmergencyToast(alert);
            this.markAlertAsSeen(alert.id);
          }
        });
      }
    } catch (err) {
      console.error('Failed to fetch geofenced emergency broadcasts:', err);
    }
  }

  markAlertAsSeen(alertId) {
    this.seenAlertIds.add(alertId);
    sessionStorage.setItem(
      'seen_geofence_alerts',
      JSON.stringify(Array.from(this.seenAlertIds))
    );
  }

  esc(t) {
    const d = document.createElement('div');
    d.textContent = t == null ? '' : String(t);
    return d.innerHTML;
  }

  renderEmergencyToast(alert) {
    const container = document.getElementById('emergencyToastContainer');
    if (!container) return;

    const severity = String(alert.severity || 'WARNING').toUpperCase();
    const isCritical = severity === 'CRITICAL';
    const borderColor = isCritical ? 'border-rose-500/80' : 'border-amber-500/80';
    const badgeBg = isCritical ? 'bg-rose-500/20 text-rose-400 border-rose-500/30' : 'bg-amber-500/20 text-amber-400 border-amber-500/30';
    const pulseBg = isCritical ? 'bg-rose-500' : 'bg-amber-500';
    const safeId = this.esc(alert.id);

    const toast = document.createElement('div');
    toast.className = `pointer-events-auto p-4 rounded-2xl bg-slate-900/90 backdrop-blur-xl border ${borderColor} shadow-2xl transition-all duration-500 transform translate-y-4 opacity-0`;
    toast.setAttribute('id', `toast-${safeId}`);
    toast.setAttribute('role', 'alert');

    toast.innerHTML = `
      <div class="flex items-start justify-between gap-3">
        <div class="flex items-center gap-2">
          <span class="relative flex h-3 w-3">
            <span class="animate-ping absolute inline-flex h-full w-full rounded-full ${pulseBg} opacity-75"></span>
            <span class="relative inline-flex rounded-full h-3 w-3 ${pulseBg}"></span>
          </span>
          <span class="text-xs font-mono font-semibold px-2 py-0.5 rounded-full border ${badgeBg}">
            ${this.esc(severity)} EMERGENCY
          </span>
        </div>
        <button onclick="dismissToast('toast-${safeId}')" class="text-slate-400 hover:text-slate-100 transition-colors" aria-label="Dismiss">
          <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/>
          </svg>
        </button>
      </div>

      <div class="mt-2 space-y-1">
        <h4 class="text-sm font-bold text-slate-100">${this.esc(alert.title)}</h4>
        <p class="text-xs text-slate-300 leading-relaxed">${this.esc(alert.message)}</p>
      </div>
    `;

    container.appendChild(toast);

    // Smooth fade-in, then auto-fade-out and remove after 30 s
    setTimeout(() => {
      toast.classList.remove('translate-y-4', 'opacity-0');
    }, 50);
    setTimeout(() => { toast.classList.add('opacity-0', 'translate-y-4'); }, 30000);
    setTimeout(() => toast.remove(), 35000);
  }
}

function dismissToast(toastId) {
  const toast = document.getElementById(toastId);
  if (!toast) return;
  toast.classList.add('opacity-0', 'translate-y-4');
  setTimeout(() => toast.remove(), 500);
}

// Auto-initialize only when geolocation permission was already granted —
// never trigger a site-wide permission popup from every page load.
document.addEventListener('DOMContentLoaded', () => {
  const boot = (allowPrompt) => {
    const sirenListener = new GeofenceSirenListener(15); // poll every 15 s
    if (allowPrompt) { sirenListener.init(); return; }
    if (navigator.permissions && navigator.permissions.query) {
      navigator.permissions.query({ name: 'geolocation' }).then((state) => {
        if (state.state === 'granted') sirenListener.init();
      }).catch(() => { /* permissions API unavailable — stay silent */ });
    }
  };
  boot(false);
  window.SkyCastGeofence = { start: boot, dismissToast };
});