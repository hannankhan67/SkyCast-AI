/**
 * SkyCast AI — Simulation Audit History Updater
 * ----------------------------------------------------------------------------
 * Polls the rule-engine dry-run history endpoint and renders the glassmorphic
 * "Simulation Audit Logs" table on the analyst dashboard. Supports manual
 * refresh, 10-second auto-polling, and instant refresh after each dry-run.
 */

let historyPollInterval = null;

/**
 * Initializes the history updater and sets up auto-polling.
 * @param {number} pollIntervalMs Polling frequency in ms (default: 10s)
 */
function initAuditLogTracker(pollIntervalMs = 10000) {
  // Fetch immediately on load
  loadSimulationHistory();

  // Set up periodic background polling
  if (historyPollInterval) clearInterval(historyPollInterval);
  historyPollInterval = setInterval(loadSimulationHistory, pollIntervalMs);
}

/**
 * Fetches recent simulation records (SQLite via the Flask analytics API).
 * @param {number} limit Max records to render (default: 10)
 */
async function loadSimulationHistory(limit = 10) {
  const tbody = document.getElementById('simulationHistoryBody');
  if (!tbody) return;

  const syncIcon = document.getElementById('historySyncIcon');
  if (syncIcon) syncIcon.classList.add('rotate-180');

  try {
    const response = await fetch(`/api/v1/analytics/simulate-alert/history?limit=${limit}`);

    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }

    const json = await response.json();
    const records = json.data || [];

    renderAuditLogRows(records);
  } catch (error) {
    console.error('Failed to update simulation audit log:', error);
    if (tbody.children.length === 1 && tbody.innerText.includes('Loading')) {
      tbody.innerHTML = `
        <tr>
          <td colspan="6" class="px-5 py-6 text-center text-rose-400/80 bg-rose-500/5">
            Unable to sync audit logs. Verify the analytics API connection.
          </td>
        </tr>
      `;
    }
  } finally {
    if (syncIcon) {
      setTimeout(() => syncIcon.classList.remove('rotate-180'), 300);
    }
  }
}

/**
 * Builds dynamic HTML rows for the audit table.
 * @param {Array<Object>} records Simulation history documents
 */
function renderAuditLogRows(records) {
  const tbody = document.getElementById('simulationHistoryBody');
  if (!tbody) return;

  if (records.length === 0) {
    tbody.innerHTML = `
      <tr>
        <td colspan="6" class="px-5 py-8 text-center text-slate-500">
          No simulation runs recorded yet. Launch the simulator to trigger a dry-run test.
        </td>
      </tr>
    `;
    return;
  }

  tbody.innerHTML = records.map(record => {
    const params = record.parameters || {};
    const severityBadge = renderSeverityBadge(record.highest_severity);
    const timeFormatted = formatTimestamp(record.executed_at);
    const triggeredCount = record.triggered_count || 0;

    return `
      <tr class="hover:bg-white/[0.02] transition-colors group">
        <!-- City -->
        <td class="px-5 py-3 font-medium text-slate-100 capitalize">
          <span class="inline-flex items-center gap-1.5">
            <span class="w-1.5 h-1.5 rounded-full bg-sky-400"></span>
            ${escapeHtml(record.city || '\u2014')}
          </span>
        </td>

        <!-- Parameters -->
        <td class="px-5 py-3 font-mono text-[11px]">
          <div class="flex flex-wrap gap-1.5">
            <span class="px-1.5 py-0.5 rounded bg-slate-800/80 border border-white/5 text-slate-300">
              ${params.temperature ?? '--'}°C
            </span>
            <span class="px-1.5 py-0.5 rounded bg-slate-800/80 border border-white/5 text-slate-300">
              AQI ${params.aqi ?? '--'}
            </span>
            <span class="px-1.5 py-0.5 rounded bg-slate-800/80 border border-white/5 text-slate-300">
              ${params.wind_speed ?? '--'} km/h
            </span>
          </div>
        </td>

        <!-- Triggered Rules Count -->
        <td class="px-5 py-3 text-center">
          <span class="inline-flex items-center justify-center w-6 h-6 rounded-full font-mono font-bold text-[11px] ${
            triggeredCount > 0
              ? 'bg-amber-500/20 text-amber-300 border border-amber-500/30'
              : 'bg-slate-800 text-slate-400 border border-white/5'
          }">
            ${triggeredCount}
          </span>
        </td>

        <!-- Highest Severity Badge -->
        <td class="px-5 py-3">
          ${severityBadge}
        </td>

        <!-- Processing Latency -->
        <td class="px-5 py-3 font-mono text-slate-400 text-[11px]">
          ${record.processing_latency_ms ?? '--'} ms
        </td>

        <!-- Execution Time -->
        <td class="px-5 py-3 text-right font-mono text-slate-400 text-[11px]">
          ${timeFormatted}
        </td>
      </tr>
    `;
  }).join('');
}

/**
 * Returns glassmorphic badge HTML for severity levels.
 * @param {string} severity CRITICAL | HIGH | WARNING | NONE
 */
function renderSeverityBadge(severity) {
  const level = (severity || 'NONE').toUpperCase();
  let classes = 'bg-slate-500/10 text-slate-400 border-slate-500/20';

  if (level === 'CRITICAL') {
    classes = 'bg-red-500/20 text-red-300 border-red-500/30';
  } else if (level === 'HIGH') {
    classes = 'bg-orange-500/20 text-orange-300 border-orange-500/30';
  } else if (level === 'WARNING') {
    classes = 'bg-amber-500/20 text-amber-300 border-amber-500/30';
  }

  return `
    <span class="inline-block px-2 py-0.5 rounded text-[10px] font-mono font-semibold uppercase border ${classes}">
      ${level}
    </span>
  `;
}

/**
 * Converts ISO timestamps into readable relative or clock time.
 * @param {string} isoString Executed-at timestamp
 */
function formatTimestamp(isoString) {
  if (!isoString) return '--:--';
  const date = new Date(isoString);
  if (isNaN(date.getTime())) return isoString;

  const now = new Date();
  const diffSec = Math.floor((now - date) / 1000);

  if (diffSec < 60) return 'Just now';
  if (diffSec < 3600) return `${Math.floor(diffSec / 60)}m ago`;
  if (diffSec < 86400) return `${Math.floor(diffSec / 3600)}h ago`;

  return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

/**
 * HTML-escapes a value for safe interpolation into table cells.
 * @param {*} str Value to escape
 */
function escapeHtml(str) {
  return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

// Expose helpers to inline handlers and the analyst toolkit module.
window.initAuditLogTracker = initAuditLogTracker;
window.loadSimulationHistory = loadSimulationHistory;
window.renderAuditLogRows = renderAuditLogRows;

// Auto-initialize when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
  initAuditLogTracker(10000);
});