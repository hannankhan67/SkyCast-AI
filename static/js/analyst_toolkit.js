/**
 * SkyCast AI — Analyst Toolkit Controller
 * Annotations · Heatmap · MAE/RMSE · Alert simulator · Hadoop jobs · Export · Audit.
 */
const AnalystToolkit = (() => {
  'use strict';

  const el = (id) => document.getElementById(id);
  const esc = (s) => String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

  const severityColor = (sev) =>
    sev === 'hazardous' ? 'bg-red-500/20 border-red-400/40 text-red-200'
      : sev === 'warning' ? 'bg-amber-500/20 border-amber-400/40 text-amber-200'
        : 'bg-teal-500/20 border-teal-400/40 text-teal-200';

  const cellColor = (status) =>
    status === 'red' ? 'bg-red-500/20 border-red-400/40 text-red-200'
      : status === 'amber' ? 'bg-amber-500/20 border-amber-400/40 text-amber-200'
        : 'bg-teal-500/20 border-teal-400/40 text-teal-200';

  /* ---- 1.1 Annotations ---- */
  async function loadAnnotations() {
    const list = el('annotation-list');
    if (!list) return;
    try {
      const r = await fetch('/api/telemetry/annotations');
      if (!r.ok) return;
      const rows = await r.json();
      list.innerHTML = rows.length ? rows.map((a) =>
        `<span class="inline-flex items-center gap-1.5 px-2 py-1 rounded-full border text-[10px] ${severityColor(a.severity)}">` +
        `${esc(a.timestamp)} · ${esc(a.label)} · ${esc(a.author)}` +
        `<button data-ann-id="${a.id}" class="ann-del ml-1 opacity-60 hover:opacity-100">✕</button></span>`
      ).join('') : '<p class="text-[10px] text-sky-100/40 font-light">No incident pins yet.</p>';
      list.querySelectorAll('.ann-del').forEach((btn) => {
        btn.addEventListener('click', async () => {
          const rr = await fetch('/api/telemetry/annotations/' + btn.dataset.annId,
                                 { method: 'DELETE' });
          if (rr.ok) loadAnnotations();
        });
      });
    } catch (e) { /* offline: keep placeholder */ }
  }

  function bindAnnotationForm() {
    const add = el('annotation-add');
    if (!add) return;
    add.addEventListener('click', async () => {
      const label = el('annotation-label').value.trim();
      const tsVal = el('annotation-ts').value;
      if (!label || !tsVal) return;
      const ts = tsVal.replace('T', ' ') + ':00';
      const r = await fetch('/api/telemetry/annotations', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ label, timestamp: ts, severity: 'info' })
      });
      if (r.ok) {
        el('annotation-label').value = '';
        loadAnnotations();
      }
    });
  }

  /* ---- 1.2 Endpoint heatmap ---- */
  async function loadHeatmap() {
    const grid = el('heatmap-grid');
    if (!grid) return;
    try {
      const r = await fetch('/api/telemetry/endpoint-matrix');
      if (!r.ok) return;
      const { rows } = await r.json();
      grid.innerHTML = rows.length ? rows.map((row) =>
        `<div class="flex items-center justify-between gap-2 px-2 py-1 rounded-lg border ${cellColor(row.status)}">` +
        `<span class="font-mono truncate">${esc(row.path)}</span>` +
        `<span class="font-mono whitespace-nowrap">${row.requests} req · ${row.avg_latency}ms` +
        `${row.errors_4xx ? ' · ' + row.errors_4xx + ' 4xx' : ''}${row.errors_5xx ? ' · ' + row.errors_5xx + ' 5xx' : ''}</span></div>`
      ).join('') : '<p class="text-sky-100/40 font-light">No traffic in the last 24h.</p>';
    } catch (e) { /* offline */ }
  }

  /* ---- 2.1 Forecast accuracy (MAE / RMSE) ---- */
  async function loadAccuracy() {
    const maeEl = el('mae-value');
    if (!maeEl) return;
    try {
      const r = await fetch('/api/telemetry/model-accuracy?window=168');
      if (!r.ok) return;
      const d = await r.json();
      maeEl.textContent = d.mae == null ? '—' : d.mae + ' °C';
      el('rmse-value').textContent = d.rmse == null ? '—' : d.rmse + ' °C';
      el('accuracy-cities').innerHTML = d.cities.length ? d.cities.map((c) =>
        `<div class="flex justify-between px-2 py-1 rounded-lg bg-white/5 border border-white/10">` +
        `<span>${esc(c.city)}</span><span class="font-mono">n=${c.count} · MAE ${c.mae} · RMSE ${c.rmse}</span></div>`
      ).join('') : '<p class="text-sky-100/40 font-light">No verifications recorded yet — add one below.</p>';
    } catch (e) { /* offline */ }
  }

  function bindVerifyForm() {
    const add = el('fv-add');
    if (!add) return;
    add.addEventListener('click', async () => {
      const body = {
        city: el('fv-city').value.trim(),
        predicted_temp: el('fv-pred').value,
        actual_temp: el('fv-actual').value
      };
      const r = await fetch('/api/telemetry/verify-forecast', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body)
      });
      if (r.ok) { el('fv-pred').value = ''; el('fv-actual').value = ''; loadAccuracy(); }
    });
    el('accuracy-refresh').addEventListener('click', loadAccuracy);
  }

  /* ---- 2.2 Extreme alert simulator (dry-run) ---- */
  function bindSimulator() {
    const run = el('sim-run');
    if (!run) return;
    run.addEventListener('click', async () => {
      const out = el('sim-result');
      const r = await fetch('/api/telemetry/simulate-alert', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          city: el('sim-city').value.trim(),
          metric: el('sim-metric').value,
          threshold: el('sim-threshold').value
        })
      });
      if (!r.ok) return;
      const d = await r.json();
      out.textContent = JSON.stringify(d, null, 2);
      out.classList.remove('hidden');
      // Instant-refresh the audit history after a successful dry-run.
      if (typeof loadSimulationHistory === 'function') {
        loadSimulationHistory();
      }
    });
  }

  /* ---- 3.1 Hadoop job runner ---- */
  let hadoopTimer = null;
  function bindHadoop() {
    const run = el('hadoop-run');
    if (!run) return;
    run.addEventListener('click', async () => {
      const r = await fetch('/api/telemetry/hadoop/jobs', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ type: el('hadoop-type').value })
      });
      if (!r.ok) return;
      const { job } = await r.json();
      el('hadoop-status').classList.remove('hidden');
      el('hadoop-id').textContent = job.job_id + ' (' + job.type + ')';
      if (hadoopTimer) clearInterval(hadoopTimer);
      hadoopTimer = setInterval(async () => {
        const rr = await fetch('/api/telemetry/hadoop/jobs/' + job.job_id);
        if (!rr.ok) { clearInterval(hadoopTimer); return; }
        const j = await rr.json();
        el('hadoop-map').textContent = j.map_progress;
        el('hadoop-reduce').textContent = j.reduce_progress;
        el('hadoop-state').textContent = j.status;
        el('hadoop-map-bar').style.width = j.map_progress + '%';
        if (j.status === 'SUCCESS') clearInterval(hadoopTimer);
      }, 1000);
    });
  }

  /* ---- 3.2 Data exporter ---- */
  function bindExport() {
    const csv = el('export-csv');
    if (!csv) return;
    csv.addEventListener('click', () => {
      const rng = el('export-range').value || 168;
      window.location.href = '/api/telemetry/export?format=csv&range=' + rng;
    });
    const json = el('export-json');
    if (json) {
      json.addEventListener('click', (e) => {
        e.preventDefault();
        const rng = el('export-range').value || 168;
        window.location.href = '/api/telemetry/export?format=json&range=' + rng;
      });
    }
  }

  /* ---- 4.2 Audit log ---- */
  async function loadAudit() {
    const list = el('audit-list');
    if (!list) return;
    try {
      const r = await fetch('/api/telemetry/audit-log?limit=25');
      if (!r.ok) return;
      const { entries } = await r.json();
      list.innerHTML = entries.length ? entries.map((a) =>
        `<div class="flex justify-between gap-2 px-2 py-1 rounded-lg bg-white/5 border border-white/10">` +
        `<span>${esc(a.action)}${a.detail ? ' — ' + esc(a.detail) : ''}</span>` +
        `<span class="font-mono whitespace-nowrap text-sky-100/40">${esc(a.author)} · ${esc(a.created_at)}</span></div>`
      ).join('') : '<p class="text-sky-100/40 font-light">No analyst actions yet.</p>';
    } catch (e) { /* offline */ }
  }

  /* ---- init ---- */
  function init() {
    bindAnnotationForm();
    bindVerifyForm();
    bindSimulator();
    bindHadoop();
    bindExport();
    loadAnnotations();
    loadHeatmap();
    loadAccuracy();
    loadAudit();
    // refresh the read-only panels alongside the live poll cadence
    setInterval(() => { loadHeatmap(); loadAudit(); }, 15000);
  }

  document.addEventListener('DOMContentLoaded', init);

  return { loadAnnotations, loadHeatmap, loadAccuracy, loadAudit };
})();