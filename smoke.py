"""End-to-end smoke test: boots SkyCast AI on a free port and probes
every route, writing a summary report to smoke-report.txt."""
import os
import sys
import time
import json
import urllib.request
import urllib.error
import urllib.parse
import subprocess
from http.cookiejar import CookieJar

PORT = 8099
BASE = "http://127.0.0.1:%d" % PORT
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "smoke-report.txt")
lines = []


def log(msg):
    lines.append(str(msg))


def get(url, timeout=30, opener=None):
    req = urllib.request.Request(url)
    with (opener or urllib.request.build_opener()).open(req, timeout=timeout) as r:
        return r.status, r.read().decode("utf-8", "replace")


def no_redirect():
    class _NR(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a, **k):
            return None
    return urllib.request.build_opener(_NR)


env = dict(os.environ)
env["SKYCAST_PORT"] = str(PORT)
# Hermetic test DB: never pokes the real data/skycast.db during a smoke run.
env["SKYCAST_DB"] = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "smoke.db"
)
SERVER_LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "smoke-server.log")
try:
    os.remove(SERVER_LOG)
except OSError:
    pass
_logf = open(SERVER_LOG, "wb")
proc = subprocess.Popen(
    [sys.executable, "-u", "app.py"],
    cwd=os.path.dirname(os.path.abspath(__file__)),
    env=env,
    stdout=_logf,
    stderr=_logf,
)
try:
    time.sleep(6)

    # 1. Homepage
    try:
        st, html = get(BASE + "/")
        log("INDEX status=%d len=%d" % (st, len(html)))
        log("INDEX has SkyCast: %s" % ("SkyCast" in html))
        log("INDEX leftover markers: %d" % html.count("SKYCAST-"))
        log("INDEX has terminal: %s" % ("root@skycast-hdfs" in html))
        log("INDEX has clouds: %s" % ("cloud cloud-slow" in html))
    except Exception as e:
        log("INDEX ERROR: %r" % e)

    # 2. Weather API (live or simulated)
    try:
        st, body = get(BASE + "/api/weather?city=karachi")
        w = json.loads(body)
        log("WEATHER status=%d live=%s temp=%s cond=%s fc=%d icon=%s" % (
            st, w["live"], w["temp"], w["condition"], len(w["forecast"]), w["icon"]))
        log("WEATHER first day=%s max=%s icon=%s" % (
            w["forecast"][0]["day"], w["forecast"][0]["max"], w["forecast"][0]["icon"]))
        if w["humidity"] is None:
            log("WEATHER humidity missing!")
    except Exception as e:
        log("WEATHER ERROR: %r" % e)

    # 3. Unknown city -> 404
    try:
        get(BASE + "/api/weather?city=atlantis")
        log("WEATHER unknown-city: expected 404 but got 200")
    except urllib.error.HTTPError as e:
        log("WEATHER unknown-city 404: %s" % e.code)
    except Exception as e:
        log("WEATHER unknown-city ERROR: %r" % e)

        # 4a. Public pages
    for path, marker in [
        ("/maps", "forecastMap"),
        ("/weather", "hourly-grid"),
        ("/analytics", "term-cursor"),
        ("/about", "SkyCast"),
    ]:
        try:
            st, html = get(BASE + path)
            log("PAGE %s status=%d len=%d marker=%s" % (path, st, len(html), marker in html))
        except Exception as e:
            log("PAGE %s ERROR: %r" % (path, e))

    # 4b. Live WeatherRadar (/maps) is a PUBLIC page, whereas the Premium
    #     pages (Specialized / Insights) are login-protected for anonymous
    #     visitors -> 302 /login. Locked premium URLs never leak a 200.
    for path in ("/solar", "/predictions"):
        try:
            get(BASE + path, opener=no_redirect())
            log("PAGE %s (anon): expected 302 but got 200" % path)
        except urllib.error.HTTPError as e:
            log("PAGE %s (anon) status=%d redirect=%s" % (path, e.code, e.headers.get("Location", "")))

    # 4c. Dashboard is protected (anonymous -> 302)
    try:
        get(BASE + "/dashboard", opener=no_redirect())
    except urllib.error.HTTPError as e:
        log("DASHBOARD (anon) status=%d redirect=%s" % (e.code, e.headers.get("Location", "")))

    # 4c. Admin console: anonymous locked out, then log in on the UNIFIED page
    admin_email = os.environ.get("ADMIN_EMAIL", "admin@skycast.ai")
    admin_pass = os.environ.get("ADMIN_PASSWORD", "")
    if not admin_pass:
        # Reuse the auto-generated password stored by the app on first boot.
        cred_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "admin-credentials.txt")
        try:
            with open(cred_file, "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip().startswith("password="):
                        admin_pass = line.strip().split("=", 1)[1]
                        break
        except OSError:
            admin_pass = "SkyCastAdmin#2026"  # legacy fallback

    try:
        get(BASE + "/admin", opener=no_redirect())
    except urllib.error.HTTPError as e:
        log("ADMIN (anon) status=%d redirect=%s" % (e.code, e.headers.get("Location", "")))

    try:
        cj = CookieJar()
        opener = urllib.request.build_opener(
            urllib.request.HTTPRedirectHandler,
            urllib.request.HTTPCookieProcessor(cj),
        )

        def getc(path, timeout=30):
            with opener.open(BASE + path, timeout=timeout) as r:
                return r.status, r.read().decode("utf-8", "replace")

        # Unified login: admins use the SAME /login page as users.
        data = urllib.parse.urlencode({"email": admin_email, "password": admin_pass}).encode()
        opener.open(BASE + "/login", data=data, timeout=30)

        st, html = getc("/admin")
        log("ADMIN (logged in) status=%d len=%d has-user-table=%s" % (st, len(html), "user-table" in html))
        log("ADMIN controls: %s" % all(k in html for k in ("broadcast-form", "refresh-users", "user-table")))
        st, body = getc("/admin/api/stats")
        s = json.loads(body)
        log("ADMIN stats users=%s api=%s alerts=%s" % (s["total_users"], s["api_calls_today"], s["active_alerts"]))
        st, body = getc("/admin/api/usage")
        u = json.loads(body)
        log("ADMIN usage points=%d first=%s last=%s" % (len(u["values"]), u["labels"][0], u["labels"][-1]))
        st, body = getc("/admin/api/users")
        us = json.loads(body)
        log("ADMIN users endpoint entries=%d" % len(us.get("users", [])))
        st, body = getc("/admin/api/logs")
        ls = json.loads(body)
        log("ADMIN logs endpoint entries=%d" % len(ls.get("logs", [])))
    except Exception as e:
        log("ADMIN ERROR: %r" % e)

    # 4d. Disaster response page is Premium-gated (Insights) -> anonymous 302;
    #     the /api/disaster data endpoint stays public.
    try:
        get(BASE + "/disaster", opener=no_redirect())
        log("DISASTER (anon) status=200 expected 302")
    except urllib.error.HTTPError as e:
        log("DISASTER (anon) status=%d redirect=%s" % (e.code, e.headers.get("Location", "")))
    except Exception as e:
        log("DISASTER (anon) ERROR: %r" % e)
    try:
        st, body = get(BASE + "/api/disaster?city=karachi")
        d = json.loads(body)
        log("DISASTER api status=%d level=%s shelters=%d helplines=%d" % (
            st, d.get("level"), len(d.get("shelters", [])), len(d.get("helplines", []))))
    except Exception as e:
        log("DISASTER api ERROR: %r" % e)

    # 4e. Alerts page is login-protected
    try:
        get(BASE + "/alerts", opener=no_redirect())
    except urllib.error.HTTPError as e:
        log("ALERTS (anon) status=%d redirect=%s" % (e.code, e.headers.get("Location", "")))

    # 4f. Developer API: key required on /api/v1/*
    try:
        get(BASE + "/api/v1/weather?city=karachi")
        log("V1 no-key: expected 401 but got 200")
    except urllib.error.HTTPError as e:
        log("V1 no-key status=%d" % e.code)

    try:
        cj2 = CookieJar()
        op = urllib.request.build_opener(
            urllib.request.HTTPRedirectHandler,
            urllib.request.HTTPCookieProcessor(cj2),
        )
        data = urllib.parse.urlencode({
            "name": "Smoke Tester",
            "email": "smoke%d@skycast.test" % int(time.time()),
            "password": "SmokePass#2026",
            "confirm_password": "SmokePass#2026",
        }).encode()
        with op.open(BASE + "/signup", data=data, timeout=30):
            pass
        key_req = urllib.request.Request(
            BASE + "/api/keys",
            data=json.dumps({"name": "smoke"}).encode(),
            headers={"Content-Type": "application/json"},
        )
        with op.open(key_req, timeout=30) as r:
            key_body = json.loads(r.read().decode())
        raw_key = key_body.get("key", "")
        log("API KEY created id=%s raw=%s.." % (key_body.get("id"), raw_key[:8]))

        def get_h(url, headers, timeout=30):
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.build_opener().open(req, timeout=timeout) as r:
                return r.status, r.read().decode("utf-8", "replace")

        st, body = get_h(BASE + "/api/v1/weather?city=karachi", {"X-API-Key": raw_key})
        v = json.loads(body)
        log("V1 with-key status=%d weather_city=%s api_version=%s" % (
            st, v.get("data", {}).get("city"), v.get("meta", {}).get("api_version")))

        # 4g. Alert lifecycle: create + test against live weather
        alert_req = urllib.request.Request(
            BASE + "/api/alerts",
            data=json.dumps({
                "city": "karachi", "metric": "wind", "operator": ">",
                "threshold": 0, "channels": ["browser"],
            }).encode(),
            headers={"Content-Type": "application/json"},
        )
        with op.open(alert_req, timeout=30) as r:
            alert_created = json.loads(r.read().decode())
        log("ALERT created id=%s ok=%s" % (alert_created.get("id"), alert_created.get("ok")))
        with op.open(BASE + "/api/alerts/test", data=b"{}", timeout=60) as r:
            fired_body = json.loads(r.read().decode())
        log("ALERT test fired=%d" % len(fired_body.get("fired", [])))
    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode("utf-8", "replace")[:4000]
        except Exception:
            body = ""
        log("ALERT/V1 HTTP %d: %s" % (e.code, body))
    except Exception as e:
        log("ALERT/V1 ERROR: %r" % e)

    # 5. Static assets
    for path in ("/static/css/style.css", "/static/js/app.js", "/static/icons/sun.svg",
                 "/static/icons/logo.svg", "/static/icons/cloud.svg", "/static/icons/rain.svg",
                 "/static/icons/snow.svg", "/static/icons/storm.svg", "/static/icons/fog.svg"):
        try:
            st, body = get(BASE + path, timeout=10)
            log("ASSET %s status=%d len=%d" % (path.rsplit("/", 1)[-1], st, len(body)))
        except Exception as e:
            log("ASSET %s ERROR: %r" % (path, e))
finally:
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except Exception:
        proc.kill()
    try:
        _logf.close()
    except Exception:
        pass

# what the terminal's JS "live tail" would consume:
log("JS keys fetch targets: /api/weather, /api/analytics")

report = "\n".join(lines)
with open(OUT, "w", encoding="utf-8") as f:
    f.write(report)
print(report)
