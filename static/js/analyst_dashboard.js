/**
 * SkyCast AI — Analyst Telemetry Dashboard Controller
 * Handles Chart.js setup, live polling, keyboard shortcuts, and UI modals.
 */
const AnalystDashboard = (() => {
  // Private State
  let chart = null;
  let pollingIntervalId = null;
  let isPolling = true;

  // DOM Elements Cache
  const elements = {
    canvas: () => document.getElementById('api-telemetry-chart'),
    totalRequests: () => document.getElementById('kpiTotalRequests'),
    avgLatency: () => document.getElementById('kpiAvgLatency'),
    activeKeys: () => document.getElementById('kpiActiveKeys'),
    successRate: () => document.getElementById('kpiSuccessRate'),
    livePulse: () => document.getElementById('livePulse'),
    badge: () => document.getElementById('telemetryBadge'),
    source: () => document.getElementById('telemetrySource'),
    pollingBtn: () => document.getElementById('pollingToggleBtn'),
    pollingBtnText: () => document.getElementById('pollingBtnText'),
    pollingBtnIcon: () => document.getElementById('pollingBtnIcon'),
    shortcutsModal: () => document.getElementById('shortcutsModal'),
    shortcutsModalCard: () => document.getElementById('shortcutsModalCard')
  };

  /**
   * Initializes the dashboard with server-bootstrapped JSON data.
   */
  function init() {
    const dataContainer = document.getElementById('telemetry-bootstrap-data');
    if (!dataContainer) return;

    try {
      const initialData = JSON.parse(dataContainer.textContent);
      initChart(initialData);
      startPolling();
      bindKeyboardShortcuts();
    } catch (err) {
      console.error('Failed to initialize Analyst Telemetry Dashboard:', err);
    }
  }

  /**
   * Initializes Chart.js line graph with dark glassmorphism styling.
   */
  function initChart(data) {
    const canvas = elements.canvas();
    if (!canvas) return;

    const ctx = canvas.getContext('2d');
    const grad = ctx.createLinearGradient(0, 0, 0, 360);
    grad.addColorStop(0, 'rgba(45, 212, 191, 0.25)');
    grad.addColorStop(1, 'rgba(129, 140, 248, 0.04)');

    chart = new Chart(ctx, {
      type: 'line',
      data: {
        labels: data.chart_labels,
        datasets: [
          {
            label: 'Request Volume',
            data: data.chart_requests,
            borderColor: 'rgba(45, 212, 191, 0.95)',
            backgroundColor: grad,
            fill: true,
            tension: 0.35,
            borderWidth: 2,
            pointRadius: 0,
            pointHoverRadius: 6,
            yAxisID: 'y'
          },
          {
            label: 'Latency (ms)',
            data: data.chart_latencies,
            borderColor: 'rgba(6, 182, 212, 0.95)',
            borderDash: [4, 4],
            fill: false,
            tension: 0.35,
            borderWidth: 2,
            pointRadius: 0,
            pointHoverRadius: 6,
            yAxisID: 'y1'
          }
        ]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: { duration: 600 },
        interaction: { mode: 'index', intersect: false },
        plugins: {
          legend: { labels: { color: 'rgba(224, 242, 254, 0.75)', font: { family: 'Inter, sans-serif', size: 12 } }, align: 'end' },
          tooltip: { backgroundColor: 'rgba(15, 23, 42, 0.92)', borderColor: 'rgba(255, 255, 255, 0.15)', borderWidth: 1, titleColor: '#e0f2fe', bodyColor: '#bae6fd', padding: 12, cornerRadius: 12, displayColors: false }
        },
        scales: {
          x: { grid: { color: 'rgba(255, 255, 255, 0.06)' }, ticks: { color: 'rgba(224, 242, 254, 0.55)', font: { family: 'Inter' } } },
          y: { beginAtZero: true, position: 'left', grid: { color: 'rgba(255, 255, 255, 0.06)' }, ticks: { color: 'rgba(224, 242, 254, 0.55)', font: { family: 'Inter' } } },
          y1: { beginAtZero: true, position: 'right', grid: { drawOnChartArea: false }, ticks: { color: 'rgba(6, 182, 212, 0.8)' } }
        }
      }
    });
  }

  /**
   * Asynchronously polls telemetry data from Flask JSON feed.
   */
  async function pollTelemetryData() {
    try {
      const response = await fetch('/api/telemetry/live-data');
      if (!response.ok) return;

      const data = await response.json();

      // Pulse visual indicator
      const pulse = elements.livePulse();
      if (pulse) {
        pulse.classList.remove('opacity-0');
        setTimeout(() => pulse.classList.add('opacity-0'), 800);
      }

      // Update KPI text nodes
      if (elements.totalRequests()) elements.totalRequests().textContent = data.total_requests.toLocaleString();
      if (elements.avgLatency()) elements.avgLatency().textContent = data.avg_latency + ' ms';
      if (elements.activeKeys()) elements.activeKeys().textContent = data.active_keys;
      if (elements.successRate()) elements.successRate().textContent = data.success_rate;

      // Update Chart.js datasets
      if (chart) {
        chart.data.labels = data.chart_labels || [];
        chart.data.datasets[0].data = data.chart_requests || [];
        chart.data.datasets[1].data = data.chart_latencies || [];
        chart.update();
      }

      // Update the source badge (Live vs Simulated) & source line
      const badge = elements.badge();
      const source = elements.source();
      if (badge && source && data.is_simulated !== undefined) {
        if (!data.is_simulated) {
          badge.className = 'inline-flex items-center gap-2 px-3 py-1 rounded-full bg-emerald-500/10 border border-emerald-500/30 shadow-sm shadow-emerald-500/10';
          badge.innerHTML = '<span class="relative flex h-2 w-2"><span class="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span><span class="relative inline-flex rounded-full h-2 w-2 bg-emerald-500"></span></span><span class="text-xs font-semibold text-emerald-300 tracking-wide uppercase">Live Telemetry</span>';
          source.textContent = 'Source: SQLite (data/skycast.db)';
        } else {
          badge.className = 'inline-flex items-center gap-2 px-3 py-1 rounded-full bg-amber-500/10 border border-amber-500/30 shadow-sm shadow-amber-500/10';
          badge.innerHTML = '<span class="relative flex h-2 w-2"><span class="animate-ping absolute inline-flex h-full w-full rounded-full bg-amber-400 opacity-75"></span><span class="relative inline-flex rounded-full h-2 w-2 bg-amber-500"></span></span><span class="text-xs font-semibold text-amber-300 tracking-wide uppercase">Simulated Data</span>';
          source.textContent = 'Source: Dynamic Fallback Generator';
        }
      }
    } catch (err) {
      console.warn('Telemetry polling skipped:', err);
    }
  }

  /**
   * Polling Control Methods
   */
  function startPolling() {
    if (pollingIntervalId) clearInterval(pollingIntervalId);
    pollingIntervalId = setInterval(pollTelemetryData, 5000);
    isPolling = true;
    updatePollingUI();
  }

  function stopPolling() {
    if (pollingIntervalId) {
      clearInterval(pollingIntervalId);
      pollingIntervalId = null;
    }
    isPolling = false;
    updatePollingUI();
  }

  function togglePolling() {
    if (isPolling) {
      stopPolling();
      showToast('Polling Paused (Alt + P)');
    } else {
      pollTelemetryData();
      startPolling();
      showToast('Polling Resumed (Alt + P)');
    }
  }

  function updatePollingUI() {
    const btn = elements.pollingBtn();
    const text = elements.pollingBtnText();
    const icon = elements.pollingBtnIcon();
    if (!btn || !text || !icon) return;

    if (isPolling) {
      btn.className = 'inline-flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-medium bg-slate-800/80 hover:bg-slate-700/80 text-teal-300 border border-teal-500/30 hover:border-teal-500/60 transition-all shadow-sm active:scale-95 cursor-pointer';
      text.textContent = 'Pause Polling';
      icon.innerHTML = '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10 9v6m4-6v6m7-3a9 9 0 11-18 0 9 9 0 0118 0z" />';
    } else {
      btn.className = 'inline-flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-medium bg-amber-500/10 hover:bg-amber-500/20 text-amber-300 border border-amber-500/40 transition-all shadow-sm active:scale-95 cursor-pointer';
      text.textContent = 'Resume Polling';
      icon.innerHTML = '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z" /><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />';
    }
  }

  /**
   * Mode Switching (Live vs Simulated)
   */
  async function toggleTelemetryMode() {
    const btn = elements.pollingBtn();
    if (btn) btn.classList.add('opacity-50', 'pointer-events-none');

    try {
      const response = await fetch('/api/telemetry/toggle', { method: 'POST' });
      if (response.ok) {
        window.location.reload();
      } else {
        showToast('Failed to toggle mode');
        if (btn) btn.classList.remove('opacity-50', 'pointer-events-none');
      }
    } catch (err) {
      console.error(err);
      if (btn) btn.classList.remove('opacity-50', 'pointer-events-none');
    }
  }

  /**
   * Shortcuts Modal Controls
   */
  function openModal() {
    const modal = elements.shortcutsModal();
    const card = elements.shortcutsModalCard();
    if (!modal || !card) return;
    modal.classList.remove('opacity-0', 'pointer-events-none');
    card.classList.remove('scale-95');
    card.classList.add('scale-100');
  }

  function closeModal() {
    const modal = elements.shortcutsModal();
    const card = elements.shortcutsModalCard();
    if (!modal || !card) return;
    modal.classList.add('opacity-0', 'pointer-events-none');
    card.classList.remove('scale-100');
    card.classList.add('scale-95');
  }

  function toggleModal() {
    const modal = elements.shortcutsModal();
    if (modal && modal.classList.contains('opacity-0')) {
      openModal();
    } else {
      closeModal();
    }
  }

  /**
   * Keyboard Event Listener Setup
   */
  function bindKeyboardShortcuts() {
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') {
        closeModal();
        return;
      }

      const activeElem = document.activeElement;
      const isTyping = activeElem && (
        activeElem.tagName === 'INPUT' ||
        activeElem.tagName === 'TEXTAREA' ||
        activeElem.isContentEditable
      );
      if (isTyping) return;

      if (e.key === '?') {
        e.preventDefault();
        toggleModal();
      } else if (e.altKey && e.key && e.key.toLowerCase() === 'p') {
        e.preventDefault();
        togglePolling();
      } else if (e.altKey && e.key && e.key.toLowerCase() === 'm') {
        e.preventDefault();
        toggleTelemetryMode();
      }
    });
  }

  /**
   * Floating Toast Notifications
   */
  function showToast(message) {
    let toast = document.getElementById('shortcutToast');
    if (!toast) {
      toast = document.createElement('div');
      toast.id = 'shortcutToast';
      toast.className = 'fixed bottom-6 right-6 z-50 px-4 py-2 rounded-lg bg-slate-800/90 text-teal-300 text-xs font-mono border border-teal-500/40 shadow-lg backdrop-blur-md transition-all duration-300 opacity-0 transform translate-y-2 pointer-events-none';
      document.body.appendChild(toast);
    }

    toast.textContent = message;
    toast.classList.remove('opacity-0', 'translate-y-2');
    setTimeout(() => toast.classList.add('opacity-0', 'translate-y-2'), 1800);
  }

  // Self-initialize on DOM ready
  document.addEventListener('DOMContentLoaded', init);

  // Public API Methods exposed to HTML onclick handlers
  return {
    togglePolling,
    toggleTelemetryMode,
    openModal,
    closeModal,
    toggleModal
  };
})();
