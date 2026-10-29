# SkyCast AI — Analyst & Admin Role Expansion Roadmap

> Captured from the proposed Analyst/Admin feature specs, cross-checked against the
> live codebase (`routes/`, `database.py`, `templates/`, `app.py`). Status tags:
> **🟢 built**, **🟡 partial** (scaffold exists, gaps noted), **🔴 new**, **⏳ blocked**.
>
> Analyst ideas = data science / forecast diagnostics; Admin ideas = governance /
> security / monetization / infra. This is a planning spec, not a diff — nothing in
> the runtime path is changed by writing it.
>
> See `docs/website-flowchart.md` §5 for the existing role/permission model.

## Status legend

| Tag | Meaning |
|---|---|
| 🟢 **Built** | Exists and is wired up. |
| 🟡 **Partial** | Scaffold exists (`database.*`, route, or template); gap + next step noted. |
| 🔴 **New** | Not present; needs schema + routes + UI. |
| ⏳ **Blocked** | Depends on infra that isn't reliably present (e.g. MongoDB mirror). |

## Analyst role — data science & forecast diagnostics

> The Analyst role (`role='analyst'` in `routes/auth.py`) unlocks the live telemetry
> dashboard (`/dashboard`, 5 s poll of `/api/telemetry/live-data`) plus read-only
> `/api/v1/analytics/system/*`. The telemetry KPIs come from
> `database.get_telemetry_kpi()` over the raw `api_requests` table written by
> `database.log_api_request()` (called from `app.py`'s `_log_api_request` after every
> `/api/*` response). Live weather is sourced from **Open-Meteo** (keyless); with a
> deterministic simulator fallback when offline.
>
> Every idea below extends that surface.

### A1 · Forecast Accuracy & Drift Matrix (MAE / RMSE Engine)

| Detail | Value |
|---|---|
| Concept | Log predicted vs. actual Open-Meteo weather every 24 h; compute MAE/RMSE for temperature & AQI per city. |
| Analyst Tool | Overlay chart: history of predictions vs. observed, plus a metrics facet. |
| Status | 🟡 Partial — `database.forecast_verification` table **already exists**; `seed_drift_data.py` seeds predicted-vs-actual rows incl. drift spikes (explicitly SQLite, not the Mongo path). |
| Gap | (1) `database.forecast_accuracy(city, metric)` computing MAE/RMSE; (2) `GET /api/analytics/forecast-accuracy`; (3) a Chart.js overlay reusing the dashboard's 5 s poll loop. |
| Next step | `AVG(ABS(pred-actual))` as MAE, `SQRT(AVG(POWER(pred-actual,2)))` as RMSE, grouped by city+metric → add to `analytics_bp`; wire a "Forecast Accuracy" tab in the analyst dashboard. |

### A2 · Alert Rule Engine — Dry-Run Sandbox

| Detail | Value |
|---|---|
| Concept | Analysts input hypothetical spikes (T 47 °C, wind 90 km/h, AQI 350) and see which disaster rules fire — before pushing live. |
| Status | 🟡 Partial — `weather_alerts`, `broadcast_alerts`, and `GET /api/alerts/active` (the toast stack) exist, plus severity tiers. |
| Gap | The rule predicates are not exposed as an evaluable function. |
| Next step | Add a server-side `_evaluate_alert_rules(conditions) -> [fired]` and `POST /api/alerts/dry-run {city?, conditions:{temp,wind,uv,aqi}}` returning `{fired:[{rule,severity,message}]}` with **no DB write**. |

### A3 · Custom Composite Index Builder

| Detail | Value |
|---|---|
| Concept | Combine temp + humidity + wind into Heat Stress Index / Wildfire Danger Rating / Crop Thermal Stress, surfaced as spatial map layers. |
| Status | 🔴 New formula library on top of 🟢 existing Leaflet maps, the `/aqi` layer, and Open-Meteo air-quality + humidity + wind variables. |
| Gap | (1) an `indices.py` calculator module; (2) an endpoint returning scalar + bbox/hexbin for the map layer switcher. |
| Next step | Ship Heat Index (Rothmueller) first — one endpoint + a toggle in `weather.html`'s layer switcher. |

### A4 · Telemetry & API Latency Inspector (p95 / p99)

| Detail | Value |
|---|---|
| Concept | p50/p95/p99 latency, 4xx/5xx failure rates, per-region + per-API-key request heatmaps. |
| Status | 🟡 Partial — `get_telemetry_kpi()` already returns `total_requests, avg_latency, success_rate, active_keys, chart_requests[], chart_latencies[], is_simulated`; `log_api_request()` stores **raw** `duration_ms` per `/api/*` call in `api_requests`. The analyst dashboard already 5 s-polls `/api/telemetry/live-data`. |
| Gap | Only the **mean** `avg_latency` is surfaced today — no p95/p99; no 4xx/5xx breakdown; no region/API-key buckets. |
| Next step | Extend the KPI query with percentile aggregates over `api_requests(duration_ms)` + a `status>=400` bucket; add fields to the live-data JSON; add a "Latency" tab to `admin/dashboard.html` (analyst read-only). |

### A5 · Data Export & GeoJSON Lab

| Detail | Value |
|---|---|
| Concept | On-demand export of historical weather + telemetry logs filtered by date range + bounding box → GeoJSON / CSV / Parquet. |
| Status | 🟡 Partial — data lives in SQLite (`api_requests`, `weather_alerts`, …) with an optional Mongo `api_key_telemetry` mirror (`app.py` lines 82-96). |
| Gap | No export endpoint; no bbox filter; no GeoJSON/Parquet writers. |
| Next step | `GET /api/analytics/export?format=geojson|csv|parquet&start=&end=&bbox=minLat,minLon,maxLat,maxLon` (streamed, analyst/admin-gated, row-capped). Parquet needs `pandas`+`pyarrow` (new deps — OK, `scikit-learn` is already declared). |

---

## Admin role — governance / security / monetization / infra

> Admin = `session['is_admin']` (see `routes/admin_features.py` `_require_admin`) →
> `/admin/*` console + `/api/admin/*` JSON feeds. The command-center page already hosts
> the feature-flag, alert, and API-key tabs (`admin/command-center.html`).

### A6 · Geofenced Emergency Broadcast Siren

| Detail | Value |
|---|---|
| Concept | Draw a polygon / radius on the Leaflet map to push a real-time banner/toast to users inside the zone only. |
| Status | 🔴 New targeting on top of 🟡 existing `broadcast_alerts` table + `GET /api/alerts/active` toast stack. |
| Gap | Broadcasts are currently global (`target_city` column), not geo-fenced. |
| Next step | Add `lat_min/max + lon_min/max` (or WKT polygon) columns to `broadcast_alerts`; have `GET /api/alerts/active` filter by the requesting user's last-known coords / city bbox. |

### A7 · Granular API Key Tiering & Quota Manager

| Detail | Value |
|---|---|
| Concept | Per-developer plans, usage caps, IP blacklisting, one-click key suspension. |
| Status | 🟡 Partial — `routes/admin_features.py manage_api_keys()` already GET/PATCH keys with `_TIER_LIMITS = {Free:60, Pro:500, Enterprise:5000}` written to `tier + rate_limit_rpm + is_active`. |
| Gap | (1) no IP blacklist column; (2) limits are stored but not hard-enforced per key; (3) no per-key usage dashboard. |
| Next step | Add `blacklisted_ips TEXT` + `quota_used / quota_reset_at` to `api_keys`; enforce in the API-key middleware; surface per-key usage in the command-center. |

### A8 · Immutable Admin Audit Log

| Detail | Value |
|---|---|
| Concept | Tamper-evident log of all admin actions: role changes, flag toggles, key revocations, with timestamp + admin id + IP + user-agent. |
| Status | 🔴 New — no audit table exists today. |
| Gap | `system_feature_flags` records `updated_at` but not *who*; `manage_api_keys` PATCH has no logging; role changes (`routes/admin.py` role endpoint) aren't audited. |
| Next step | `CREATE TABLE admin_audit_log (id, actor_id, action, target, ip, user_agent, created_at)` + a `log_admin_action()` helper called at each admin mutation. Optional: a `checksum` column for tamper evidence. |

### A9 · Database Sync & Cache Management Console

| Detail | Value |
|---|---|
| Concept | Show SQLite↔Mongo sync lag, trigger manual `VACUUM`, clear in-memory caches on demand. |
| Status | 🟡 Partial — both stores exist: `data/skycast.db` (SQLite) and the optional `api_key_telemetry` Mongo mirror (`app.py` lines 82-96; `telemetry_col is None` when Mongo is unreachable). |
| Gap | No sync-lag metric; no admin cache-clear action; no vacuum action. |
| Next step | `GET /admin/api/system/mirror-status` (last-written ts + lag); `POST` to run `VACUUM` on SQLite; the Flask app reads config rather than a hot cache, so "cache clear" is restart-dependent unless a cache layer is introduced later. |

### A10 · Feature Flag & Canary Deployment Panel

| Detail | Value |
|---|---|
| Concept | Toggle routes/UI components on/off globally **or** for a % of users (canary). |
| Status | 🟡 Partial — `system_feature_flags` table + `GET/POST /api/admin/feature-flags` and `_FLAG_DEFAULTS` in `routes/admin_features.py` exist. But flags are **app-wide booleans only** — no per-route targeting, no percentage rollout. |
| Gap | (1) no `canary_pct` / `target_route` columns; (2) route-level checks aren't flag-gated (only `/agriculture` uses `premium_required`). |
| Next step | Extend the flags table with `target_route TEXT, canary_pct INTEGER, cohort_cookie TEXT`; add a `feature_enabled(key, user_id)` helper (per-user roll); gate a route/UI component on it. |

---

## Roles affected (existing vs. proposed)

| Idea | Who does it | Leverages existing infra |
|---|---|---|
| A1 Forecast Accuracy | Analyst | `forecast_verification` + analyst dashboard poll |
| A2 Alert Dry-Run | Analyst | `weather_alerts` / `broadcast_alerts` |
| A3 Composite Indices | Analyst | Open-Meteo vars + Leaflet layers |
| A4 Latency Inspector | Analyst | `api_requests` raw rows already logged |
| A5 Data Export | Analyst / Admin | SQLite + optional Mongo |
| A6 Geo Broadcast | Admin | `broadcast_alerts` table |
| A7 Key Tiering | Admin | `api_keys` + `manage_api_keys` |
| A8 Audit Log | Admin | — (new table) |
| A9 Sync & Cache | Admin | `data/skycast.db` + Mongo |
| A10 Feature Flags | Admin | `system_feature_flags` + `command-center` |

## Implementation priority (suggested)

| Priority | Items | Rationale |
|---|---|---|
| 1 · quick wins | A4, A7-gap, A10-gap | Data already logged/stored; only a percentile query / a column + enforcement is missing. |
| 2 · medium | A1, A2, A9, A6 | Reuse existing tables + the 5 s dashboard poll / Leaflet maps; need an endpoint or a column. |
| 3 · heavy | A3, A5, A8 | A3 = formula + layer work; A5 = new exporters (+deps); A8 = new immutable table + call-site wiring. |

> Notes: (a) this workspace is **not a git repo** (`fatal: not a git repository`),
> so these docs are flat files under `docs/` — no PR/branch workflow yet; (b) MongoDB is
> **optional** (`telemetry_col is None` when unreachable) — any feature depending on it
> should degrade gracefully (⏳); (c) `smoke.py` already asserts premium routes
> (`/solar`, `/predictions`) 302 to `/login` for anonymous users and never leak a 200
> — preserve that invariant when gating new routes behind `premium_required`
> (`routes/auth.py:142`).

