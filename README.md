# SkyCast AI — Breathing Sky Climate Dashboard ☁️

[![Cypress E2E Telemetry Tests](https://github.com/USERNAME/REPOSITORY/actions/workflows/cypress-e2e.yml/badge.svg?branch=main)](https://github.com/USERNAME/REPOSITORY/actions/workflows/cypress-e2e.yml?query=branch%3Amain)

A competition-ready weather application with a **breathing-sky glassmorphism** UI,
**floating parallax clouds**, a **macOS-style Hadoop/HDFS analytics terminal**, and a
**real live weather API** (Open-Meteo, no API key required).

## Tech Stack

- **Backend:** Flask 3 (Python 3.12)
- **Frontend:** Tailwind CSS v4 (Play CDN `@tailwindcss/browser@4`), vanilla JS, custom CSS
- **Data API:** [Open-Meteo](https://open-meteo.com) — live, keyless
- **Big-Data Showcase:** simulated Hadoop Cluster + HDFS ingest / MapReduce pipeline

## Run it

**Easiest — double-click** `C:\skycast-ai\start.bat`
(opens the browser automatically; auto-picks a free port)

**Or from the terminal** (works from ANY folder now):

```powershell
python C:\skycast-ai\app.py
```

> The app resolves its own `templates/` and `static/` folders relative to
> `app.py`, so it no longer matters which directory your terminal is in.

**Port:** SkyCast **auto-picks a browser-safe free port** (default **8080**).
Browsers refuse some ports with `ERR_UNSAFE_PORT` (notably 5060/5061 — SIP),
so those are never used. To force a specific port:

```powershell
$env:SKYCAST_PORT = "8080"
python C:\skycast-ai\app.py
```

Then open the URL the console prints, e.g. **http://127.0.0.1:8080**.

## Features

- **User accounts** — session-based login / signup with a split-screen
  glassmorphism UI (`/login`, `/signup`), password hashing (werkzeug/scrypt),
  SQLite storage (`data/skycast.db`, auto-created)
- **Forgot password that really works** — `/forgot-password` emails a
  single-use 6-digit verification code (hashed in DB, expires in 15 min);
  `/reset-password` verifies the code and updates the password. Configure
  SMTP via `.env` (see `.env.example`); without SMTP the code is printed in
  the server console (dev mode)
- **Breathing sky background** — 15s `linear-gradient` pan animation (`@keyframes breathing-sky`)
- **Floating parallax clouds** — 4 cloud objects at 45s / 60s / 90s / 120s drift speeds
  (pure CSS, GPU-accelerated `transform`, layered behind glass cards at `-z-10`)
- **Frosted-glass dashboard** — `backdrop-blur`, translucent white borders, `rounded-[2.5rem]` cards,
  editorial typography (font-light temps, `uppercase tracking-widest`, opacity-based secondary text)
- **Climate Analytics Engine** — glassmorphism server terminal (`root@skycast-hdfs ~ -bash`)
  with macOS traffic-light dots, cascading CSS boot logs, and a JS "live tail"
- **Admin Console** (`/admin`) — Flask Blueprint + Chart.js: 3 glass stat cards, a curved
  gradient-filled "API Usage Overview" line chart, users table, live API log terminal,
  glass toggles, and a collapsible mobile sidebar
- **Live weather & 7-day forecast** — `/api/weather?city=karachi|lus|islamabad|dubai|london|newyork`,
  with a deterministic offline simulator fallback so the demo never breaks
- **Radar widget** — animated CSS sweep + echo blobs
- **Accessibility** — `prefers-reduced-motion` disables the ambient animations

## API

| Endpoint | Description |
|---|---|
| `/` | Landing / hero dashboard |
| `/login` | Log in (split-screen) |
| `/signup` | Create account (split-screen) |
| `/logout` | Log out |
| `/forgot-password` | Request a 6-digit reset code by email |
| `/reset-password` | Verify code + set a new password |
| `/weather` | Live Weather page (hourly + 7-day + stats) |
| `/maps` | Radar & layer maps (precipitation / cloud / wind) |
| `/analytics` | Climate Analytics Engine (Hadoop / HDFS showcase) |
| `/dashboard` | Personal user dashboard (saved cities) |
| `/about` | About + tech stack |
| `/admin` | Admin Console (stats + Chart.js API usage) |
| `/api/weather?city=karachi` | Live weather + hourly + 7-day forecast (current, daily) |
| `/api/analytics` | Mock HDFS cluster status (12 datanodes, MapReduce jobs) |
| `/admin/api/stats` | Admin headline metrics (users, API calls, alerts) |
| `/admin/api/usage` | 24-hour API request series for the Chart.js line chart |

## Login & "Forgot password" email setup

The auth system needs **no extra pip packages** — it uses Flask sessions,
werkzeug hashing (bundled with Flask) and Python's stdlib `smtplib`.

To make the emailed verification code actually arrive in an inbox:

1. `copy .env.example .env`
2. Fill in your SMTP details (a **Gmail App Password** works great — see the
   comments inside `.env.example`). Port `587` = STARTTLS, `465` = SSL.
3. Restart the app. Forgot-password codes are now delivered by email with a
   branded HTML template.

> **Dev mode:** if `.env` / SMTP vars are missing, no email is sent — the
> 6-digit code is printed in the server console so you can still complete
> the flow locally.

Security details: codes are stored **hashed** (never plaintext), expire after
**15 minutes**, are **single-use**, and requesting a new code invalidates all
previous ones. The forgot-password page always responds identically whether
or not the email is registered (no account enumeration).

## Smoke test

```powershell
python smoke.py    # boots app on port 8099, probes every route, writes smoke-report.txt
```