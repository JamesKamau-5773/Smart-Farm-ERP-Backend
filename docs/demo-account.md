# Public demo account: API contract

A visitor clicks **Try the live demo** and lands in a read-only copy of a
realistic farm ("Silato Farm") without registering. The backend decides
everything; the frontend only renders what the API returns.

## Start a demo session

`POST /api/auth/demo`

- No body and no credentials. Send it with `credentials: 'include'` so the
  session cookie is stored, the same as for `POST /api/auth/login`.
- The session is created by the same machinery as a normal login: the access
  token arrives in the httpOnly `access_token_cookie` (plus the CSRF cookie
  when CSRF protection is on) and in the response body.

### 200 OK

The same shape as a successful `POST /api/auth/login`, plus the demo fields:

```json
{
  "access_token": "<jwt>",
  "session_expires_at": "2026-11-13T10:45:00Z",
  "is_demo": true,
  "read_only": true,
  "name": "Demo Visitor",
  "role": "FARMER",
  "tenant_id": "tenant_7",
  "tenant_name": "Silato Farm",
  "farm_id": "farm_9",
  "farm_name": "Silato Farm",
  "available_farms": [{ "id": "farm_9", "name": "Silato Farm" }],
  "page_access": ["breeding", "customers", "dashboard", "..."],
  "auth_state": "ACTIVE",
  "account_flags": { "...": "..." }
}
```

`page_access` covers every page except `member_admin`.

### Errors

| Status | `code` | When |
|---|---|---|
| 404 | (generic not found) | The demo is switched off (`DEMO_ENABLED` is not `True`). Hide the button. |
| 429 | `RATE_LIMITED` | Too many demo starts from this IP. Honour `Retry-After`. Default limit: 5 per minute and 20 per hour. |
| 503 | `DEMO_UNAVAILABLE` | The demo is on but its data has not been prepared yet. |

## Session lifetime

- A demo session lasts **45 minutes** by default (`DEMO_SESSION_MINUTES`) and
  cannot be refreshed. When it expires, requests return 401 like any expired
  session. Offer "Restart demo" (another `POST /api/auth/demo`) or "Create an
  account".
- `session_expires_at` (ISO 8601, UTC) is in the login response and in
  `GET /api/auth/me`, so the frontend can show a countdown.
- `POST /api/auth/logout` works normally and ends only this visitor's session.

## Current user: fields added to `GET /api/auth/me`

These fields now appear for **every** user. Render from them; never infer demo
status from the name, the tenant or the token.

| Field | Type | Meaning |
|---|---|---|
| `is_demo` | boolean | This session belongs to the public demo. Show the demo banner. |
| `read_only` | boolean | Every write will be refused. Hide or disable create, edit and delete controls. |
| `session_expires_at` | string or null | When this session's token expires (ISO 8601, UTC). |

`is_demo` and `read_only` are also in the `POST /api/auth/login` and
`POST /api/auth/demo` responses. Both are `false` for normal accounts.

## What a demo session can do

Read every module: dashboard, production, tasks, herd, breeding, medical, feed
and feeding, customers and buyers, finance, inventory, reports, safety, staff
and payroll.

The server refuses everything else, whatever the UI shows:

| Status | `code` | Applies to |
|---|---|---|
| 403 | `DEMO_READ_ONLY` | Any `POST`, `PUT`, `PATCH` or `DELETE`. This includes profile edits, password changes, phone verification, switching farm and inviting users. |
| 403 | `DEMO_FEATURE_UNAVAILABLE` | Exports and downloads (PDF and CSV: animal passport, receipts, payslips), member and workspace administration, and linking a Google account. |

Both errors have the same body:

```json
{ "code": "DEMO_READ_ONLY", "error": "This is a read-only demo. Create a free account to record your own farm data.", "demo": true }
```

Show `error` as a friendly prompt to sign up rather than as a failure.

These routes stay open during a demo session, so a visitor can leave the demo
without logging out first: `POST /api/auth/logout`, `POST /api/auth/demo`,
`POST /api/auth/login`, `POST /api/auth/register`, the password-recovery
routes, and Google sign-up.

## Data

- One demo farm with 15 cows. About 75 days of milk records, averaging 40–50
  L a day. Also breeding and heat records, vet visits, one cow under a
  mastitis withdrawal, feed recipes and yield targets, stock with one item
  below its reorder level, buyers and customers with outstanding balances,
  income and expenses, three staff with payroll, and daily routine logs.
- Every date is relative to today. The data is rebuilt automatically by the
  first demo start of each day, so the frontend never needs to handle stale
  demo data.
- All names and figures are invented. Demo customers' phone numbers are
  placeholders such as `DEMO-0001`, not real numbers.
