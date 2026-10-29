# SkyCast AI — Feedback & Support Flowchart

> Rendered from the live codebase (`routes/support.py`, `database.py`, `mailer.py`,
> `templates/support.html`, `templates/support_ticket.html`). Open this file in
> **VS Code with the Mermaid preview** (or GitHub) to see the diagrams rendered.
>
> Covers the `support_bp` blueprint only — see [`website-flowchart.md`](website-flowchart.md)
> for the whole site.

---

## 1. Master Flowchart (routes, guards, templates, data layer)

```mermaid
flowchart TD
    %% ================= GLOBAL MIDDLEWARE =================
    subgraph MW["app.py — global middleware (every request)"]
        BR["before_request: session user_id → g.user (or None)"]
        AR1["after_request: security headers (nosniff, DENY, no-store)"]
        AR2["after_request: path starts with /api/<br/>→ insert api_logs telemetry row (failures swallowed)"]
    end

    U([🌐 Visitor / Signed-in user]) --> BR --> NAV

    NAV{"Which support request?"}

    NAV -->|"GET /support"| GATE
    NAV -->|"POST /api/support/tickets"| GATE
    NAV -->|"GET /support/&lt;id&gt;"| GATE
    NAV -->|"POST /api/support/&lt;id&gt;/reply"| GATE

    GATE{"@login_required<br/>g.user not None?"}
    GATE -->|"No"| REDIR["flash 'Please log in to access that page.'<br/>302 → /login?next=&lt;path&gt;"]
    GATE -->|"Yes"| LIST["support_page() — GET /support<br/>render templates/support.html"]

    %% ================= READ PATHS =================
    LIST --> Q_LIST["database.get_support_tickets_for_user(g.user.id)<br/>JOIN users → user_name, newest updated_at first"]
    Q_LIST --> V_LIST["list of tickets + categories[] + priorities[]<br/>+ #support-form (new ticket)"]

    GATE -->|"Yes"| THREAD["support_ticket_page(ticket_id)<br/>GET /support/&lt;id&gt;"]
    THREAD --> Q_ONE["database.get_support_ticket(id, user_id=g.user.id)<br/>scoped query → other users' tickets look missing"]
    Q_ONE -->|"None"| NF["404 + render support.html<br/>error='Ticket not found.'"]
    Q_ONE -->|"Row"| Q_REP["database.get_support_replies(id)<br/>JOIN users → author_name, created_at ASC"]
    Q_REP --> V_THREAD["render templates/support_ticket.html<br/>conversation + #reply-form<br/>(form hidden when status == 'closed')"]

    %% ================= WRITE PATHS =================
    GATE -->|"Yes"| CREATE["api_create_ticket()<br/>POST /api/support/tickets"]
    GATE -->|"Yes"| REPLY["api_reply(ticket_id)<br/>POST /api/support/&lt;id&gt;/reply"]

    CREATE --> W_INS["database.create_support_ticket(...)<br/>INSERT status='open' → COMMITS"]
    W_INS --> W_REP["database.add_support_reply(..., is_staff=False)<br/>INSERT reply + bump ticket.updated_at"]
    W_REP --> NOTIFY["_notify_admin_new_ticket(ticket, g.user)<br/>best-effort — never raises"]

    REPLY --> R_CHK["database.get_support_ticket(id, user_id=g.user.id)"]
    R_CHK -->|"None"| R404["404 {error: 'Ticket not found.'}"]
    R_CHK -->|"'closed'"| R409["409 {error: 'Ticket is closed.'}"]
    R_CHK -->|"'open' / 'in_progress'"| R_INS["database.add_support_reply(..., is_staff=False)<br/>INSERT + bump updated_at → 201 {ok: true, id}"]

    %% ================= DATA LAYER =================
    subgraph DBL["🗄 SQLite — data/skycast.db"]
        T1["support_tickets<br/>id · user_id · subject · category · priority<br/>status · created_at · updated_at"]
        T2["support_replies<br/>id · ticket_id · author_id · body · is_staff · created_at"]
    end
    W_INS --> T1
    W_REP --> T2
    R_INS --> T2
    Q_LIST --> T1
    Q_ONE --> T1
    Q_REP --> T2

    %% ================= MAIL =================
    subgraph MAIL["📧 mailer.py — notification path"]
        M1{"smtp_configured()?<br/>SMTP_HOST set"}
        M2["SMTP send (587 STARTTLS / 465 SSL)<br/>timeout 20s"]
        M3["DEV MODE: print [DEV MAIL] block<br/>to the server console"]
    end
    NOTIFY --> M1
    M1 -->|"yes"| M2
    M1 -->|"no"| M3

    %% ================= ADMIN DATA HELPERS =================
    subgraph HLP["Admin-side helpers (not wired to any route yet)"]
        H1["database.get_all_support_tickets(status=None)<br/>all users, urgency-ordered"]
        H2["database.count_open_tickets()<br/>status IN (open, in_progress)"]
        H3["database.update_ticket_status(id, status)<br/>open | in_progress | resolved | closed"]
    end
    T1 --> HLP

    AR2 -.->|telemetry only| CREATE
    AR2 -.->|telemetry only| REPLY
```

**Legend:** solid arrows = real control/data flow · dotted arrows = side effects that
never change the response (telemetry, mail) · 🔒 = `@login_required`.

---

## 2. Ticket Creation — `POST /api/support/tickets`

### 2.1 Current (fixed) happy path

```mermaid
flowchart TD
    SUB(["User clicks 'Submit Ticket'"]) --> JS0["#support-form submit handler<br/>e.preventDefault(); trim() the four fields"]
    JS0 --> JS1["fetch('POST /api/support/tickets')<br/>Content-Type: application/json"]
    JS1 --> GATE{"@login_required —<br/>g.user set?"}
    GATE -->|"No"| L302["302 to /login?next=/api/support/tickets<br/>fetch follows it; r.json() fails → .catch()"]
    GATE -->|"Yes"| PARSE["data = request.get_json(silent=True) or {}"]
    PARSE --> NORM["strip() subject+body · lower() category+priority"]
    NORM --> VAL{"subject AND body non-empty?"}
    VAL -->|"No"| E400["400 {'error': 'Subject and message are required.'}"]
    VAL -->|"Yes"| COERCE["unknown category → 'general'<br/>unknown priority → 'normal'"]
    COERCE --> INS["database.create_support_ticket(... )<br/>INSERT status='open' → COMMIT → ticket_id"]
    INS --> REP["database.add_support_reply(..., is_staff=False)<br/>INSERT the message + bump ticket.updated_at"]
    REP --> RELOAD["ticket = database.get_support_ticket(ticket_id)<br/>re-read the persisted row (fallback dict guards the key)"]
    RELOAD --> NOTIFY["_notify_admin_new_ticket(ticket, g.user)"]
    NOTIFY --> NOTE{"Whole body in try/except +<br/>.get() fallbacks — can't raise"}
    NOTE -->|"sent / printed / SMTP down"| DONE["201 {ok: true, id, ticket}"]
    NOTE -->|"any error"| SWALLOW["swallowed — creation still succeeds"]
    SWALLOW --> DONE
    DONE --> OK["JS: 'Ticket submitted. Redirecting…'<br/>window.location = /support/id"]
    E400 --> ERR["JS: '⚠️  ' + body.error"]
```

### 2.2 The bug path that caused the 500 (before the fix)

```mermaid
flowchart TD
    A["INSERT ticket + reply<br/>already COMMITTED by the with-block"] --> B["_notify_admin_new_ticket(<br/>{'id','category','subject'}, g.user)<br/>hand-built dict — NO 'priority' key"]
    B --> C["email f-string reads ticket['priority']<br/>— OUTSIDE the try/except"]
    C --> D["KeyError: 'priority'"]
    D --> E["500 Internal Server Error<br/>the committed ticket row stays in the DB"]
    E --> F["User sees an error → clicks Submit again"]
    F --> A
```

> One DB row landed per click. Four clicks between `11:09:27–11:09:36` → four identical
> tickets (`#1…#4`) in `data/skycast.db` for the `execelent` report. The INSERT had
> committed before the exception, so the 500 was the user-visible symptom while the write
> had already happened — which is exactly why retries multiplied the rows.

### 2.3 Before vs after

| Aspect | Before | After |
|---|---|---|
| Notification data source | hand-built dict missing `priority` | `database.get_support_ticket(ticket_id)` (fallback dict) |
| Guard scope in `_notify_admin_new_ticket` | only `mailer.send_raw(...)` | the whole function body |
| Field access | `ticket['category']`, `ticket['priority']` | `.get()` → `general` / `normal` / `(no subject)` |
| `None` or non-dict `ticket`/`user` arg | crash | `dict(ticket or {})` normalises |
| SMTP failure | already tolerant | still tolerant |
| Result when notification fails | `500` + orphan ticket | `201` + ticket persisted |

---

## 3. Threaded Replies — `POST /api/support/<id>/reply`

```mermaid
flowchart TD
    R0(["User (ticket owner) posts a reply"]) --> R1["#reply-form handler<br/>trim(); empty → '⚠️  Reply cannot be empty.'"]
    R1 --> R2["fetch POST /api/support/<id>/reply<br/>{body}"]
    R2 --> G{"@login_required<br/>g.user set?"}
    G -->|"No"| G401["302 → /login (fetch fails → .catch())"]
    G -->|"Yes"| Q["database.get_support_ticket(id, user_id=g.user.id)<br/>scoped join — cross-user = indistinguishable from missing"]
    Q -->|"None"| R404["404 {'error': 'Ticket not found.'}"]
    Q -->|"Row"| STAT{"ticket.status == 'closed'?"}
    STAT -->|"yes"| R409["409 {'error': 'Ticket is closed.'}"]
    STAT -->|"no"| INS["database.add_support_reply(id, user_id, body, is_staff=False)<br/>INSERT reply + bump ticket.updated_at"]
    INS --> DONE["201 {ok: true, id}"]
    DONE --> OK["JS: 'Reply posted. Reloading…'<br/>window.location.reload()"]

    subgraph DB["SQLite — support_replies"]
        RP["id · ticket_id · author_id · body · is_staff · created_at"]
    end
    INS --> RP
```

## 4. Ticket Status Lifecycle

```mermaid
stateDiagram-v2
    [*] --> open
    open --> in_progress
    in_progress --> open
    in_progress --> resolved
    resolved --> closed
    resolved --> open
    closed --> resolved
    closed --> in_progress
    note right of closed
      api_reply returns 409 on a closed ticket.
      support_ticket.html hides the reply form.
    end note
    note right of in_progress
      No route sets these statuses yet —
      only database.update_ticket_status(), used by tests/admin tooling.
    end note
```

## 5. Route → Status Code Matrix

> Applies to the authenticated paths (`/support`, `/support/<id>`); anonymous requests
> are redirected (302) to `/login` by `@login_required` before reaching the handler.
> All `/api/*` traffic additionally emits a telemetry row via `_log_api_request`.

| Route | Verb | Auth | Success | Failure 1 | Failure 2 | Failure 3 |
|---|---|---|---|---|---|---|
| `/support` | GET | required | `200` ticket list | (n/a) | — | — |
| `/api/support/tickets` | POST | required | `201` `{ok,id,ticket}` | `400` empty subject/body, non-JSON, non-object | `500` *(previously — KeyError)* | — |
| `/support/<id>` | GET | required | `200` thread | `404` ticket not yours / missing | — | — |
| `/api/support/<id>/reply` | POST | required | `201` `{ok,id}` | `400` empty body / non-JSON | `404` ticket missing (scoped) | `409` ticket closed |

## 6. Data Model

| Table | Columns | Notes |
|---|---|---|
| `support_tickets` | `id` · `user_id` → users · `subject` · `category` DEFAULT `general` · `priority` DEFAULT `normal` · `status` DEFAULT `open` · `created_at` · `updated_at` | index `idx_support_user(user_id, status)` |
| `support_replies` | `id` · `ticket_id` ↓ support_tickets ON DELETE CASCADE · `author_id` → users · `body` · `is_staff` DEFAULT 0 · `created_at` | index `idx_support_replies_ticket(ticket_id)` |

Valid values: `category ∈ {general, bug, feature, billing, other}`,
`priority ∈ {low, normal, high, urgent}`, `status ∈ {open, in_progress, resolved, closed}`.

## 7. Notification Sub-flow (admin email)

`_notify_admin_new_ticket(ticket, user)` → `mailer.send_raw("admin@skycast.ai", subject, body)`:

- subject = `[SkyCast Support] #{id} {CATEGORY} — {subject}`
- body carries **Priority** (the field that used to raise `KeyError`), **Category**, From, and a reminder to open the admin console.
- `mailer.send_raw` picks the transport: if `SMTP_HOST` is set → SMTP (587 STARTTLS / 465 SSL, 20 s timeout); otherwise **DEV MODE** → prints a `[DEV MAIL]` block to the console.
- The whole helper is wrapped in `try/except` and reads every field with `.get()` and a default, so **mail never breaks ticket creation**.

## 8. Regression Coverage

| Script | What it asserts | Result |
|---|---|---|
| `verify_support_tickets.py` | 44 checks: auth redirect, the `201` regression, persistence, notification content incl. the old `Priority` key, mailer-failure tolerance, malformed-input safety, validation 400s, category/priority coercion, page renders, unknown-404, thread + closed-409, cross-user isolation, admin helpers | ✅ ALL OK (44/44, exit 0) |
| `verify_changes.py` / `verify_premium_lock*.py` | unrelated modules — not affected (no route/template/decorator changed in their surface) | pre-existing pass |

Run the guard for yourself at any time:

```bash
python verify_support_tickets.py     # uses a throwaway SKYCAST_DB under %TEMP%
```


