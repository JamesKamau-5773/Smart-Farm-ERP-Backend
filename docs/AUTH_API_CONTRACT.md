# Auth API Contract

**Status:** Implemented on branch `development`. This document describes the shipped behaviour.
**Base URL:** `{API}` (for example `https://api.maziwasmart.co.ke`). Every path below is relative to it.
**Last updated:** 2026-11-02

---

## 0. Answers to the frontend's open questions

| Question | Answer |
|---|---|
| Google: ID token or redirect/callback? | **Redirect and callback.** The backend runs the OAuth flow through Authlib. The frontend sends the browser to `GET /api/auth/google/start`, and later receives it back at `{FRONTEND_BASE_URL}/auth/google/complete?result=…`. The frontend doesn't load Google's script. See §5. |
| Where does the WhatsApp number come from? | **From the API response.** Every reverse-OTP response contains `whatsapp_number` (E.164), `message_text` and a ready-made `wa_link`. Don't use `SITE.whatsapp`. The backend number differs between staging and production, and the backend is the source of truth. |
| Which fields mean "phone needed" / "phone verified"? | `auth_state` (one value that drives routing) and `account_flags` (`needs_phone`, `phone_verified`, `email_verified`, `has_password`). Both appear on login, register, switch-farm, Google sign-up and `GET /api/auth/me`. See §2. |
| How does forgot-password report available channels? | `GET /api/auth/password/forgot/options` returns the channels **enabled on the platform**. They are never per account, because a per-account answer would reveal whether the account exists. See §7.1. |
| After a WhatsApp reset, does the set-new-password screen take a code or a token? | **A token from a link.** When the user sends the `RESET-xxxxxx` code, the backend replies on WhatsApp with a link `{FRONTEND_BASE_URL}/reset-password?token=…`. Email resets and admin resets use the same screen, link format and endpoint (`POST /api/auth/password/reset`). See §7. |

---

## 1. Conventions

### 1.1 Session, cookies, CSRF (unchanged)
- On success, an auth endpoint sets the access-token cookie (HttpOnly) and the `csrf_access_token` cookie. It also returns `access_token` in the JSON body. This matches `/login` today.
- Every state-changing request made with cookie auth must send the header `X-CSRF-TOKEN: <value of csrf_access_token cookie>`. This is enforced in production, same as today.
- Send all requests with `credentials: "include"`.
- **There are no refresh tokens.** The access token lasts 2 hours. A password reset or admin reset **ends every existing session** for that user immediately. After that, any request with an old token gets `401` with `{"msg": "Token has been revoked"}`, which is Flask-JWT-Extended's existing response for revoked tokens. Treat it like an expired session.

### 1.2 Error envelope
New and changed endpoints return errors as:
```json
{ "code": "MACHINE_READABLE_CODE", "error": "Human-readable message" }
```
Older endpoints that aren't listed here still return only `{ "error": "..." }`. Switch on `code`, never on `error` text.

Common codes on every endpoint below:

| HTTP | code | Meaning |
|---|---|---|
| 400 | `VALIDATION_ERROR` | Bad or missing input. An optional `fields` object maps field name → message. |
| 400 | `INVALID_PHONE` | The phone number couldn't be parsed as a valid Kenyan or international number. |
| 400 | `WEAK_PASSWORD` | The password fails the policy (§1.4). `violations` is an array of rule ids. |
| 401 | `UNAUTHENTICATED` | No valid session. |
| 403 | `PASSWORD_RESET_REQUIRED` | Existing gate: the user must set a password first. |
| 403 | `PHONE_VERIFICATION_REQUIRED` | New gate (§2.3). |
| 429 | `RATE_LIMITED` | Too many requests. Read the `Retry-After` header (seconds). This applies to every endpoint in the API, not just auth. |

### 1.3 Phone numbers
- The frontend may send `0712345678`, `0112345678`, `712345678`, `254712345678` or `+254712345678`. Spaces and dashes are allowed.
- **The backend always returns E.164**, for example `+254712345678`.
  ⚠️ **Breaking change:** `phone_number` in login, `/me` and JWT payloads used to be `254712345678`. Update any code that formats, compares or strips it.

### 1.4 Password policy
The policy applies wherever a new password is set: register, reset, claim account, change password, admin provisioning. It is **not** applied at login, so existing passwords keep working.

| Rule id | Rule |
|---|---|
| `min_length` | At least 8 characters |
| `max_length` | At most 128 characters |
| `letter_and_digit` | Contains at least one letter and one digit |
| `not_personal` | Not equal to, and doesn't contain, the user's phone digits, email local part or username |
| `not_common` | Not on the common-password blocklist |

---

## 2. Account state signals

### 2.1 `auth_state`
One value. Route on it.

| Value | Frontend should |
|---|---|
| `ACTIVE` | Proceed normally. |
| `PASSWORD_RESET_REQUIRED` | Show the existing set-password screen (`POST /api/auth/change-password`). |
| `PHONE_VERIFICATION_REQUIRED` | Show the collect-and-verify-phone screen (§6). |

Precedence when several apply: `PASSWORD_RESET_REQUIRED` > `PHONE_VERIFICATION_REQUIRED` > `ACTIVE`.

### 2.2 `account_flags`
Informational. Use it for banners and nudges.

```json
"account_flags": {
  "needs_phone": false,
  "phone_verified": true,
  "email_verified": false,
  "has_password": true,
  "linked_providers": ["google"]
}
```

| Field | Meaning |
|---|---|
| `needs_phone` | The account has no phone. This affects older accounts and accounts whose number was flagged during migration. **Login still works.** Show a "please add your phone" banner. |
| `phone_verified` | The phone was confirmed through WhatsApp. |
| `email_verified` | The email was confirmed through a link. Email reset and Google auto-linking need this. |
| `has_password` | `false` for accounts created through Google until the user sets a password. Hide "change password" and prefer "set password" via forgot-password. |
| `linked_providers` | Social providers linked to the account. |

### 2.3 Phone-verification gate
- `auth_state` is `PHONE_VERIFICATION_REQUIRED` **only** when the current session started through Google sign-in **and** the account has no verified phone.
- Password logins never hit this gate. Those users only see the `needs_phone` banner.
- While the gate applies, every endpoint returns `403 PHONE_VERIFICATION_REQUIRED` except these:
  `GET/PATCH /api/auth/me`, `POST /api/auth/logout`, `POST /api/auth/phone/verification`, `GET /api/auth/phone/verification/{verification_id}`.
- The gate is checked against live account state. Once the phone is verified, the same session works straight away. There's no need to log in again.

---

## 3. Registration

### `POST /api/auth/register` — CHANGED
Rate limits (unchanged): 2/min and 5/10 min per IP.

Request:
```json
{
  "farm_name": "Kamau Dairy",
  "phone_number": "0712345678",
  "password": "Maziwa2026",
  "email": "jane@example.com",
  "name": "Jane Kamau",
  "username": "jane",
  "tenant_type": "single"
}
```
- `farm_name`, `phone_number` and `password` are required.
- `email` is **new and optional**. It is stored lowercased and unverified. If it's present, the backend sends a verification email.
- `name`, `username` and `tenant_type` are optional, as today.

`201 Created`:
```json
{
  "message": "Workspace registered successfully",
  "access_token": "…",
  "phone_number": "+254712345678",
  "auth_state": "ACTIVE",
  "account_flags": { "needs_phone": false, "phone_verified": false, "email_verified": false, "has_password": true, "linked_providers": [] },
  "...": "all existing payload fields (sub, name, role, tenant_id, farm_id, available_farms, page_access, …)"
}
```

Errors: `400 VALIDATION_ERROR | INVALID_PHONE | WEAK_PASSWORD`, `409 PHONE_IN_USE`, `409 EMAIL_IN_USE`, `403 BOOTSTRAP_UNAVAILABLE | INVALID_BOOTSTRAP_KEY`, `429 RATE_LIMITED`.
Existing behaviour is kept: re-registering with an existing phone **and** its correct password returns `200` with `"message": "Workspace already exists"` and a session.

---

## 4. Login

### `POST /api/auth/login` — CHANGED
Rate limits: 5/min and 10/10 min per IP (unchanged), **plus** 10 per 15 min for each login identifier (new).

Request:
```json
{ "login": "0712345678", "password": "Maziwa2026", "farm_id": "farm_3" }
```
- `login` is new. It accepts a phone in any format from §1.3, an email, or a username. The backend detects which one it is.
- The legacy fields `username` and `phone_number` still work. `email` is also accepted. Precedence: `login` > `email` > `phone_number` > `username`.
- `farm_id` is optional and only matters for cooperatives (unchanged).

`200 OK`: the existing payload plus `auth_state` and `account_flags` (§2).

Errors:

| HTTP | code | Notes |
|---|---|---|
| 400 | `VALIDATION_ERROR` | Missing identifier or password |
| 401 | `INVALID_CREDENTIALS` | Same response for an unknown user and a wrong password |
| 403 | `ACCOUNT_DISABLED` | |
| 400 | `INVALID_FARM` | `farm_id` doesn't belong to the tenant |
| 429 | `RATE_LIMITED` | |

### `GET /api/auth/me` — CHANGED
Adds `email`, `auth_state`, `account_flags` and `farm_timezone` (IANA name such as `"Africa/Nairobi"`; farm calendar dates follow it). `phone_number` is E.164 or `null`. Other fields are unchanged. These values are read live from the database, so this is the right call to make after verifying a phone or email.

### `PATCH /api/auth/me` — CHANGED
- Body as today (`name`, `farm_location`, `phone_number`), plus `email`.
- Changing `phone_number` saves it straight away, unverified (existing behaviour), and resets `phone_verified` to `false`. To change number without losing verified status in between, use `POST /api/auth/phone/verification` with the new number instead.
- Changing `email` resets `email_verified` to `false` and sends a new verification email.
- The response adds `email` and `account_flags`.
- Errors: `400 INVALID_PHONE`, `400 VALIDATION_ERROR` (bad email), `409 PHONE_IN_USE`, `409 EMAIL_IN_USE`.

### `POST /api/auth/switch-farm`, `POST /api/auth/change-password`, `POST /api/auth/claim-account` — CHANGED (additive)
- Success responses gain `auth_state` and `account_flags`.
- `change-password` and `claim-account` enforce the password policy and can return `400 WEAK_PASSWORD`.

---

## 5. Google sign-in (redirect flow)

### 5.1 Flow
```
Frontend                         Backend                              Google
  │ window.location = /api/auth/google/start?intent=signin&next=/dashboard
  │───────────────────────────────▶│ 302 ─────────────────────────────▶│ consent
  │                                │◀──────── /api/auth/google/callback│
  │◀── 302 {FRONTEND_BASE_URL}/auth/google/complete?result=…&next=…    │
  │ then: GET /api/auth/me  (or GET /api/auth/google/pending-signup)
```
- The redirect URL never contains a token or personal data. Only `result`, `error_code` and `next` are passed.
- A session cookie, if any, has already been set by the callback response.

### `GET /api/auth/google/start` — NEW (browser navigation, not fetch)

| Query | Required | Values |
|---|---|---|
| `intent` | no | `signin` (default) or `link` (requires an existing session; adds Google to the logged-in account) |
| `next` | no | A frontend path starting with `/`. Absolute URLs are dropped (prevents open redirects). It's echoed back on completion. |

Rate limit: 10/min per IP.

### `GET /api/auth/google/callback` — NEW (Google only, not called by the frontend)

### 5.2 Completion redirect: `{FRONTEND_BASE_URL}/auth/google/complete?result=<result>[&error_code=<code>][&next=<path>]`

| `result` | Session set? | What happened | Frontend should |
|---|---|---|---|
| `signed_in` | yes | Google is linked and the account has a verified phone | `GET /me`, then go to `next` |
| `phone_verification_required` | yes (gated) | Signed in, but no verified phone. **This is the "needs phone" state.** | `GET /me` (it returns `auth_state: PHONE_VERIFICATION_REQUIRED`), then show the phone screen (§6) |
| `signup_required` | no | No account matches this Google identity | `GET /api/auth/google/pending-signup`, then show the sign-up form |
| `link_required` | no | A local account has this email, but **that email isn't verified**, so the backend won't auto-link | Tell the user: "Log in with your phone and password, then link Google in Settings." |
| `linked` | (existing) | `intent=link` succeeded | Show a success message |
| `error` | no | See `error_code` | Show an error |

`error_code` values: `GOOGLE_CANCELLED`, `GOOGLE_STATE_MISMATCH`, `GOOGLE_EMAIL_UNVERIFIED` (Google itself hasn't verified the email), `GOOGLE_ALREADY_LINKED` (this Google identity belongs to another account, or the account already has a different Google identity), `ACCOUNT_DISABLED`, `GOOGLE_UNAVAILABLE` (also returned when Google sign-in isn't configured), `UNAUTHENTICATED` (`intent=link` without a valid session).

Auto-link rule: Google is linked to an existing account automatically **only** if Google reports the email as verified **and** the local account's `email_verified` is `true`.

### `GET /api/auth/google/pending-signup` — NEW
- Reads the short-lived pending-signup cookie that the callback set. It lasts 10 minutes and is HttpOnly.
- `200`:
```json
{ "signup_token": "…opaque…", "email": "jane@gmail.com", "name": "Jane Kamau", "expires_in_seconds": 540 }
```
- `404 SIGNUP_SESSION_EXPIRED`: send the user back to `/google/start`.

### `POST /api/auth/google/signup` — NEW
Rate limit: 5/10 min per IP.

```json
{ "signup_token": "…", "farm_name": "Kamau Dairy", "phone_number": "0712345678", "name": "Jane Kamau", "tenant_type": "single" }
```
- `signup_token`, `farm_name` and `phone_number` are required.
- The account is created with `email_verified: true` (Google verified it), `phone_verified: false` and `has_password: false`.

`201`: same shape as register, with `auth_state: "PHONE_VERIFICATION_REQUIRED"`, **plus** a `phone_verification` object. The backend has already started verification for the submitted phone, so the frontend can show the code straight away:
```json
{
  "message": "Workspace registered successfully",
  "access_token": "…",
  "auth_state": "PHONE_VERIFICATION_REQUIRED",
  "account_flags": { "needs_phone": false, "phone_verified": false, "email_verified": true, "has_password": false, "linked_providers": ["google"] },
  "phone_verification": { "verification_id": "pv_…", "status": "pending", "message_text": "VERIFY-482913", "whatsapp_number": "+254700000000", "wa_link": "https://wa.me/254700000000?text=VERIFY-482913", "expires_at": "…", "expires_in_seconds": 600, "phone_number": "+254712345678" },
  "...": "all other existing payload fields"
}
```
Poll `GET /api/auth/phone/verification/{phone_verification.verification_id}` as in §6.
If another account holds the number but never verified it, `account_flags.needs_phone` is `true` until verification completes (§6).

Errors: `400 VALIDATION_ERROR | INVALID_PHONE`, `401 SIGNUP_SESSION_EXPIRED`, `409 PHONE_IN_USE`, `409 EMAIL_IN_USE`, `429`.

### `DELETE /api/auth/social/google` — NEW (authenticated)
- Unlinks Google. `200 { "message": "Google account unlinked", "account_flags": {…} }`.
- `409 LAST_LOGIN_METHOD`: the account has no password, so unlinking would lock the user out.
- `404 NOT_FOUND`: no Google account is linked.

---

## 6. Phone verification (WhatsApp reverse OTP)

### 6.1 Flow
1. The frontend calls **start**. It receives `message_text` (for example `VERIFY-482913`), `whatsapp_number` and `wa_link`.
2. The user taps the `wa_link`. WhatsApp opens with the message pre-filled, and the user presses send. Show the code too, so it can be typed by hand.
3. The backend's WhatsApp webhook checks that **the sender's number equals the phone being verified** and that the code matches. It marks the phone verified and replies on WhatsApp ("✅ Your phone number is verified…"). A wrong code or an expired challenge gets an "invalid or expired" reply.
4. The frontend polls **status** every 3–5 seconds and stops on any final state.

### `POST /api/auth/phone/verification` — NEW (authenticated; allowed through the gate)
Rate limits: 3 per 10 min and 10 per day per user, plus 5 per 10 min per phone.

```json
{ "phone_number": "0712345678" }
```
- `phone_number` is optional. If it's given, that number is verified (useful for `needs_phone` users and for changing number). If it's left out, the account's current phone is used.
- **The number is saved to the account only when verification succeeds.** Until then, the account keeps its previous phone, if any.
- **Proven possession wins.** If another account holds the same number but never verified it, a successful verification moves the number to this account. The other account is flagged `needs_phone`, and the move is audited. A number already verified on another account can't be claimed (`409 PHONE_IN_USE`).
- Starting again cancels any earlier pending verification.

`201`:
```json
{
  "verification_id": "pv_8f3a…",
  "status": "pending",
  "phone_number": "+254712345678",
  "message_text": "VERIFY-482913",
  "whatsapp_number": "+254700000000",
  "wa_link": "https://wa.me/254700000000?text=VERIFY-482913",
  "expires_at": "2026-11-02T10:10:00Z",
  "expires_in_seconds": 600
}
```

Errors: `400 INVALID_PHONE`, `400 PHONE_REQUIRED` (no body phone and none on the account), `409 PHONE_IN_USE` (verified on another account), `409 PHONE_ALREADY_VERIFIED`, `429`.
`503 CHANNEL_DISABLED`: no WhatsApp business number is configured on the server. Show "Phone verification isn't available right now" with a **Do this later** option, and don't show a code.

### `GET /api/auth/phone/verification/{verification_id}` — NEW (authenticated)
Rate limit: 60/min per user, which allows polling.

`200`:
```json
{ "verification_id": "pv_8f3a…", "status": "pending", "expires_at": "…", "attempts_remaining": 5 }
```

| `status` | Final? | Meaning |
|---|---|---|
| `pending` | no | Waiting for the WhatsApp message |
| `verified` | yes | Done. Call `GET /me` to refresh `auth_state` and `account_flags`. |
| `expired` | yes | The 10 minutes passed. Offer "start again". |
| `locked` | yes | 5 wrong codes came from this number. Offer "start again". |
| `cancelled` | yes | A newer verification replaced this one |

`404 NOT_FOUND`: the id doesn't exist or belongs to another user.

---

## 7. Forgot / reset password

Every forgot-password request returns **the same response whether or not an account exists**:
`"If an account exists, we've sent instructions."`

### 7.1 `GET /api/auth/password/forgot/options` — NEW (public)
```json
{
  "channels": [
    { "id": "whatsapp", "enabled": true, "input": "phone_number", "label": "WhatsApp" },
    { "id": "email",    "enabled": true, "input": "email",        "label": "Email" }
  ],
  "admin_reset_hint": "Staff members can also ask their farm owner or administrator to reset their password."
}
```
- This list reflects **platform configuration only**. For example, `email` is disabled if no Resend key is configured.
- The email channel only delivers if the account's email is verified. The response never says whether that happened.

### 7.2 `POST /api/auth/password/forgot` — NEW (public)
Rate limits: 5/hour per IP, plus 3/hour per phone or email.

WhatsApp:
```json
{ "channel": "whatsapp", "phone_number": "0712345678" }
```
`202` (always this shape, even if no account exists):
```json
{
  "message": "If an account exists, we've sent instructions.",
  "channel": "whatsapp",
  "message_text": "RESET-731904",
  "whatsapp_number": "+254700000000",
  "wa_link": "https://wa.me/254700000000?text=RESET-731904",
  "expires_in_seconds": 600
}
```
- The user sends the code from **their registered WhatsApp number**.
- If the account exists and the sender matches, the backend replies on WhatsApp with a reset link: `{FRONTEND_BASE_URL}/reset-password?token=…`.
- In every other case nothing happens.
- There is no status endpoint. Tell the user: "Send the message, then open the link we reply with."

Email:
```json
{ "channel": "email", "email": "jane@example.com" }
```
`202`:
```json
{ "message": "If an account exists, we've sent instructions.", "channel": "email", "expires_in_seconds": 600 }
```
The email contains the same `{FRONTEND_BASE_URL}/reset-password?token=…` link.

Errors (format problems only, never account existence): `400 VALIDATION_ERROR | INVALID_PHONE`, `400 CHANNEL_DISABLED` (that channel is off platform-wide; see §7.1), `429`.
Rate-limit buckets are shared: requests for the same phone or email from different IPs count together.

### 7.3 The reset screen: `{FRONTEND_BASE_URL}/reset-password?token=…`
WhatsApp, email and admin resets all land on this one screen.
Frontend guidance:
- Read `token` from the URL, then remove it with `history.replaceState`.
- Set `<meta name="referrer" content="no-referrer">` on this page.

### `POST /api/auth/password/reset/validate` — NEW (public)
Lets the screen show "link expired" before the user types a password.
Rate limit: 20/10 min per IP.

```json
{ "token": "…" }
```
- `200 { "valid": true, "expires_at": "…" }`
- `400 { "code": "RESET_TOKEN_INVALID", "error": "This reset link is invalid or has expired." }` covers invalid, expired, used or locked tokens, without saying which.

### `POST /api/auth/password/reset` — NEW (public)
Rate limit: 10/10 min per IP. Each token allows at most 5 failed attempts.

```json
{ "token": "…", "password": "NewPass2026", "confirm_password": "NewPass2026" }
```

`200`:
```json
{ "message": "Password updated. Please log in with your new password." }
```
- **The user isn't logged in automatically.** Redirect to login.
- All of the user's existing sessions are revoked, the token is used up, and `requires_password_reset` is cleared.

Errors: `400 RESET_TOKEN_INVALID`, `400 PASSWORD_MISMATCH`, `400 WEAK_PASSWORD`, `429`.

### 7.4 Admin / farm-owner reset

#### `POST /api/tenant/users/{user_id}/password-reset` — NEW (authenticated, CSRF)
- **Who may call it:** the farm owner (`FARMER` on a single-farm tenant), `FARM_ADMIN`, `ADMIN` (cooperative admin) and `SUPER_ADMIN`. A `FARMER` who is a member of a cooperative can't.
- **Who may be reset:** the target must be in the caller's tenant (`SUPER_ADMIN` may reset any tenant), must be active, and must rank strictly lower than the caller.
  Rank, highest first: `SUPER_ADMIN` > `ADMIN` > single-farm owner `FARMER` > `FARM_ADMIN` > cooperative-member `FARMER` > `FARM_MANAGER` > `FARM_SUPERVISOR` > `VETERINARY_DOCTOR` > `FARM_HAND`.
- **Not allowed:** resetting yourself, resetting a `SUPER_ADMIN`, or resetting an equal or higher rank (for example `FARM_ADMIN` → single-farm owner).

Rate limit: 10/hour per caller.

Request: `{}` (no body needed).

`201`:
```json
{
  "message": "Reset link created. Share it with the user directly.",
  "user": { "id": 42, "name": "Peter Otieno" },
  "reset_url": "https://www.maziwasmart.co.ke/reset-password?token=…",
  "expires_at": "2026-11-02T10:10:00Z",
  "expires_in_seconds": 600
}
```
- The target's existing sessions are revoked when the link is created.
- The link uses the same screen and endpoint as §7.3.
- Show `reset_url` once, with copy and "share on WhatsApp" buttons. It can't be fetched again.
- Every admin reset is written to the audit log.

Errors: `403 FORBIDDEN` (caller isn't an owner or admin), `403 FORBIDDEN_TARGET` (self, higher rank, super admin, or inactive account), `404 NOT_FOUND` (also returned for users in other tenants), `429`.

---

## 8. Email verification

### `POST /api/auth/email/verification` — NEW (authenticated)
Sends a verification link to the account email.
Rate limits: 3/hour per user.

- `202 { "message": "Verification email sent.", "email": "jane@example.com", "expires_in_seconds": 600 }`
- Errors: `400 EMAIL_REQUIRED`, `409 EMAIL_ALREADY_VERIFIED`, `400 CHANNEL_DISABLED`, `429`.

The link is `{FRONTEND_BASE_URL}/verify-email?token=…`. Clean the URL as in §7.3.

### `POST /api/auth/email/verification/confirm` — NEW (public)
Rate limit: 20/10 min per IP.

```json
{ "token": "…" }
```
- `200 { "message": "Email verified.", "email_verified": true }`
- `400 VERIFICATION_TOKEN_INVALID`

---

## 9. WhatsApp webhook — CHANGED behaviour (Meta only, not called by the frontend)
`POST /api/whatsapp/webhook`
- The `X-Hub-Signature-256` HMAC check is unchanged. Unsigned or invalid requests get `403`.
- Messages that match `VERIFY-\d{6}` or `RESET-\d{6}` are handled before the farm bot. Case and surrounding spaces are ignored.
- Senders are matched as E.164. A wrong code from a number that has a pending challenge uses up one attempt. After 5, the challenge is `locked`.
- The webhook always returns `200` to Meta.

---

## 10. Security parameters (for UX copy)

| Parameter | Value |
|---|---|
| Code / link lifetime | 10 minutes |
| Max failed attempts per code/token | 5 |
| Code format | `VERIFY-` or `RESET-` + 6 digits |
| Storage | Codes and tokens are stored only as HMAC hashes, never in plain text |
| Sessions after password reset | All revoked |

## 11. Endpoint index

| Method | Path | Status |
|---|---|---|
| POST | `/api/auth/register` | changed |
| POST | `/api/auth/login` | changed |
| GET | `/api/auth/me` | changed |
| PATCH | `/api/auth/me` | changed |
| POST | `/api/auth/switch-farm` | changed (additive) |
| POST | `/api/auth/change-password` | changed (password policy) |
| POST | `/api/auth/claim-account` | changed (password policy) |
| GET | `/api/auth/google/start` | new |
| GET | `/api/auth/google/callback` | new (Google only) |
| GET | `/api/auth/google/pending-signup` | new |
| POST | `/api/auth/google/signup` | new |
| DELETE | `/api/auth/social/google` | new |
| POST | `/api/auth/phone/verification` | new |
| GET | `/api/auth/phone/verification/{verification_id}` | new |
| POST | `/api/auth/email/verification` | new |
| POST | `/api/auth/email/verification/confirm` | new |
| GET | `/api/auth/password/forgot/options` | new |
| POST | `/api/auth/password/forgot` | new |
| POST | `/api/auth/password/reset/validate` | new |
| POST | `/api/auth/password/reset` | new |
| POST | `/api/tenant/users/{user_id}/password-reset` | new |
| POST | `/api/whatsapp/webhook` | changed behaviour |

## 12. Deployment notes that affect the frontend
- The frontend and API are on different sites, so session cookies need `JWT_COOKIE_SAMESITE=None` and `Secure` in production. This is already required for today's login.
- The frontend needs these routes: `/auth/google/complete`, `/reset-password`, `/verify-email`.
- The backend needs `FRONTEND_BASE_URL` set to the frontend origin used in links and redirects.

## 13. Existing users after the migration (for support and UX copy)
- **Everyone can still log in** with their existing username or phone and password.
- **Phone format:** stored numbers are converted to `+254…`. Numbers that existed only in old username or identifier fields are copied into `phone_number`.
- **Unresolved numbers:** a number that can't be assigned safely (invalid, or claimed by more than one account) is left off the account and reported to the backend team. Those users see `account_flags.needs_phone: true` and should be prompted to add and verify a phone (§6).
- **Verification flags:** every existing account starts with `phone_verified: false` and `email_verified: false`. Prompt users to verify. Email verification is needed before email reset or Google auto-linking works for them.
