# SkyCast AI — Requirements Compliance Matrix

Traceability matrix mapping the formal Functional / Non-Functional
Requirements to their implementation in this codebase, with honest status
for anything that cannot be satisfied on a single-node development stack.

Legend: ✅ implemented · 🟡 partially implemented · ⚠️ deployment-dependent
(hooks provided, needs infrastructure) · N/A outside project scope.

## Functional Requirements

| # | Requirement | Status | Implementation |
|---|---|---|---|
| FR1 | Secure authentication & role-based authorization | ✅ | Session auth (werkzeug scrypt hashing) in `routes/auth.py`; roles `user/analyst/admin` (`users.role`); `role_required`/`min_role_required` + permission **bitmask** decorators (`security/permissions.py`); admin console role management (`routes/admin.py`); immutable Mongo audit trail via `@audit_admin_action` (`security/audit.py`) |
| FR2 | Diverse data ingestion (stations, sensors, derived sources) | ✅ | Live pull: Open-Meteo weather + air-quality (`app.py`, hourly worker `scripts/sync_forecast_actuals.py`); **bulk upload**: `POST /api/analyst/ingest` accepts CSV / JSON / JSONL with row validation, plausibility bounds and skip-and-count error handling (`services/ingest.py`); historical vs real-time both flow through the same core |
| FR2b | Common climate data formats | ✅ | CSV (header row), JSON array/object, JSON Lines; ISO-8601 timestamps throughout |
| FR3 | HDFS storage, partitioning & organization | 🟡 | **Hive-partitioned data lake** `services/data_lake.py` (`city=X/dt=YYYY-MM-DD/part-*.jsonl`) — set `SKYCAST_LAKE_ROOT` to a mounted HDFS/S3/NFS volume and the layout ports unchanged. A real Hadoop cluster cannot run inside this app container; the layout + JSONL format are what HDFS/Spark ingest natively. The marketing "HDFS" pages (`templates/analytics.html`) are the *simulated* showcase |
| FR4 | MapReduce jobs for parallel processing | ✅ | `services/mapreduce.py` — generic Map/Shuffle/Reduce driver with `multiprocessing.Pool` mappers, serial fallback, shard-count-invariant composable sufficient statistics; shipped jobs: per-city **Pearson correlation** (`city_pearson_job`) and **least-squares trend** (`city_trend_job`) |
| FR4b | Pattern / anomaly / correlation algorithms | ✅ | Anomaly: Z-score detector (`services/anomaly.py`, \|Z\| ≥ 2.5 → `climate_anomalies`); Correlations: temp↔AQI / temp↔humidity / wind↔AQI; Patterns: linear climate trend (°C/day) with r² |
| FR4c | Graceful handling of missing/incomplete data | ✅ | Ingestion nulls out-of-bounds readings and skips measureless rows; analytics filter None pairs per metric; loaders fall back across stores (Mongo → SQLite); renderers/UI tolerate absent fields throughout |
| FR5 | Real-time streaming + batch integration | ✅ | **SSE** live stream computes real p50/p95/p99 + 5xx rate + req/s from `api_requests` (`routes/telemetry_sse.py`); batch side: hourly sync worker, Celery (`tasks/`) for async alert evaluation, drift backtester (`services/drift_engine.py`) — streaming feeds the same stores batch analyses |
| FR6 | ML models: prediction, anomaly, correlation; refreshed from latest data | ✅ | Trend regression trained per request on freshest observations — sklearn `LinearRegression` with closed-form fallback (`services/forecast_trends.py`); RandomForest classifier (`ml_model.py`); Z-score anomaly engine; Pearson correlation jobs. Drift (MAE/RMSE) monitoring closes the loop (`services/drift_engine.py`) |
| FR7 | Interactive dashboards & visualization | ✅ | Dashboard w/ live telemetry (Chart.js + SSE + 5 s polling), air-quality dashboard, Leaflet maps, analyst drift/anomaly APIs, admin console, command center — `templates/` + `static/js/` |
| FR8 | Automated notifications & configurable alerts | ✅ | Per-user threshold alerts (`weather_alerts`, `routes/alerts.py`) w/ severity tiers; broadcast warning center (`broadcast_alerts`, admin geofenced siren via Mongo polygons); channels: browser notifications, email (SMTP), **WhatsApp** (Meta Cloud API), SMS stub — `mailer.py`, `notifications.py`; dispatcher logs every send (`notification_log`) |
| FR9 | Feedback & support system | ✅ | Threaded support tickets with categories/priorities/status (`routes/support.py`, `support_tickets`/`support_replies`), admin email notification, ticket UI |

## Non-Functional Requirements

| # | Requirement | Status | Implementation |
|---|---|---|---|
| NFR1 | Performance monitoring & optimization | ✅ | `api_requests` telemetry table (every API call, duration_ms), KPI aggregation (`database.analyst_dashboard_telemetry`), live SSE percentiles, Redis response cache (`services/cache.py`) with graceful fallback |
| NFR2 | Data security (encryption at rest/in transit) | 🟡/⚠️ | At rest: passwords scrypt-hashed, reset codes hashed, API keys stored hashed, secrets via `.env` (gitignored), gzip'd DB backups; In transit: **TLS terminates at the reverse proxy / load balancer** (deployment concern — see notes below); security headers on every response (`app.py` `_security_headers`) |
| NFR3 | Reliability: uptime & scheduled backups | 🟡/⚠️ | **Backups**: `scripts/backup_database.py` (online SQLite backup API → gzip, retention-pruned) + admin API `POST /api/admin/data/backup`; schedule via cron — wire the schedule in deployment. **Uptime**: `restart: always` on all compose services; Mongo healthcheck; app is stateless (cookie sessions) so web replicas crash/replace freely |
| NFR4 | Horizontal scalability & load balancing | 🟡/⚠️ | App tier scales horizontally: no in-process session state, shared `.secret_key`, shared DB volume; `docker compose up --scale web=N` behind a reverse-proxy LB. SQLite is the single-node bound — swap to Postgres behind the `database._connect()` seam for multi-writer scale |
| NFR5 | Compliance with environmental data standards | 🟡 | ISO-8601 timestamps, UTC handling, consistent metric naming/units (°C, km/h, AQI), Hive-partition layout, JSONL interchange. Formal CF-NetCDF ingestion is out of scope for tabular app data (arrives via the lake path) |
| NFR6 | Monitoring of data-processing times | ✅ | `duration_ms` captured per API request; drift engine tracks model accuracy over time; SSE exposes live p95/p99; analyst dashboard charts hourly volume/latency |

## Honest gaps (not hidden)

1. **Real HDFS** — requires a Hadoop cluster; provided the port-ready
   partitioned lake (`SKYCAST_LAKE_ROOT`) instead of pretending.
2. **TLS/HTTPS** — must be terminated by nginx/ALB in the deployment;
   nothing in the app can provide it meaningfully in dev.
3. **Scheduled backup execution** — the script + admin API exist; cron /
   Task Scheduler wiring is a deployment step (example cron line inside
   the script docstring).
4. **Satellite imagery** — binary raster storage belongs in an object
   store (S3/HDFS); the ingestion endpoint handles the tabular/derived
   products (station & sensor records, AQI) that the analytics consume.