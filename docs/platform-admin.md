# Platform admin (super admin): sessions, 2FA and server-side recovery

Maziwa Smart has exactly one platform admin: the user with role `SUPER_ADMIN`. This
document covers how that account is protected and how operators recover or move it.
Farm users are not affected by anything here.

## The rules

- **One super admin.** The database allows at most one `SUPER_ADMIN` user
  (`uq_users_single_super_admin`).
- **It lives in the platform tenant** (`tenants.is_platform = true`), which is never a farm:
  it has no farm, no farm data and is never the demo. The only other accounts allowed
  there are deactivated former super admins.
- **No API endpoint can create, promote to, demote from or transfer the role.** The only
  ways are the HTTP bootstrap (when no super admin exists and it has been explicitly opened)
  and the `flask platform` commands below. A model guard
  (`app/utils/super_admin_guard.py`) refuses the change anywhere else.
- **Two-factor authentication is required** (TOTP from an authenticator app; no SMS).
- **Platform routes** (`@platform_admin_required`) pass only for the active super admin in the
  platform tenant whose current session passed 2FA. The role is read live from the database,
  never from token claims. `role_required(...)` is never satisfied by `SUPER_ADMIN`.

## Sessions

| State | Token lifetime | What it can do |
|---|---|---|
| Signed in with a password, 2FA not yet passed | 10 minutes (`PLATFORM_ADMIN_PENDING_MFA_MINUTES`) | `GET /api/auth/me`, `POST /api/auth/logout`, the three 2FA endpoints. Anything else: `403 MFA_REQUIRED`. |
| 2FA passed | 30 minutes (`PLATFORM_ADMIN_SESSION_MINUTES`) | Auth endpoints and platform endpoints. Farm routes: `403 PLATFORM_SCOPE`. |

There are no refresh tokens: when the 30 minutes end, sign in and pass 2FA again. 2FA
completion is recorded on the server (`mfa_sessions`, keyed by the token id), not in the client.
Passing 2FA issues a new token and revokes the pre-2FA one.

Platform endpoints today: `POST /api/tenant/cooperatives`,
`POST /api/tenant/cooperatives/<tenant_id>/members`, `POST /api/tenant/cooperatives/<tenant_id>/members/bulk`,
`POST /api/tenant/users/<user_id>/password-reset` (for a user in another tenant), and `GET /api/tenant/profile`.

## 2FA endpoints

All require the signed-in super admin; anyone else gets `403 MFA_NOT_AVAILABLE`. Without
`MFA_ENCRYPTION_KEYS` on the server they answer `503 MFA_NOT_CONFIGURED`.

### `POST /api/auth/mfa/enrollment`
Starts enrolment (only while not enrolled; otherwise `409 MFA_ALREADY_ENROLLED`).
```json
{ "secret": "BASE32SECRET…", "otpauth_uri": "otpauth://totp/Maziwa%20Smart:admin?secret=…&issuer=Maziwa%20Smart" }
```
Render `otpauth_uri` as a QR code; show `secret` for manual entry.

### `POST /api/auth/mfa/enrollment/confirm` `{ "code": "123456" }`
Finishes enrolment. `200` with the same body as a login (a new 30-minute session, also set as
the cookie) plus `"recovery_codes": ["abcde-fghjk", …]` (10 codes). **They are shown only
this once**; only hashes are stored. Wrong code: `401 MFA_INVALID_CODE`.

### `POST /api/auth/mfa/verify` `{ "code": "123456" }` or `{ "recovery_code": "abcde-fghjk" }`
For later sign-ins. `200` with a login body and a new 30-minute session. Each TOTP time step
and each recovery code is accepted once. Wrong code: `401 MFA_INVALID_CODE`.
Not enrolled: `409 MFA_NOT_ENROLLED`.

Rate limits on confirm and verify: 5 attempts per 5 minutes per user and 20 per hour per IP
(`429 RATE_LIMITED`).

### Fields on `GET /api/auth/me` and the login response
| Field | Farm users | Super admin |
|---|---|---|
| `is_platform_admin` | `false` | `true` once in the platform tenant |
| `mfa_enrolled` | `false` | whether an authenticator is set up |
| `mfa_verified` | `false` | whether this session passed 2FA |

Route the super admin to enrolment when `mfa_enrolled` is false, to verification when
`mfa_verified` is false, and to the platform screens otherwise.

## Server-side commands (`flask platform …`)

Run on the server (for Render: the service's Shell tab). Never exposed over HTTP. Every
command prints exactly what it would change; `--dry-run` stops there. Each change writes an
audit entry (`audit_logs`, with the reason, the OS user and the host).

| Command | What it does |
|---|---|
| `flask platform status` | Read-only: the super admin, its tenant, 2FA state, and what that tenant holds. |
| `flask platform reset-2fa --reason "…" [--dry-run]` | Deletes the super admin's authenticator secret, recovery codes and verified sessions; ends all their sessions. They enrol again at next sign-in. |
| `flask platform transfer-super-admin --to <phone> --reason "…" [--dry-run]` | Atomically demotes the current super admin (deactivated, stays in the platform tenant) and moves the account with that phone into the platform tenant as super admin. Ends both accounts' sessions. You type the phone number to confirm. Refuses demo, deactivated or staff-linked accounts and a farm's last owner. |
| `flask platform move-super-admin --reason "…" [--dry-run]` | For a super admin created before the platform tenant existed: moves the account into the platform tenant. Refuses if its current tenant holds any farm data. Changes only the account. |
| `flask platform split-super-admin --username <name> [--name …] [--email …] --reason "…" [--dry-run]` | For a super admin whose account runs a real farm: that account becomes the farm's `FARMER` (all farm data stays), and a new account (password typed at a hidden prompt) becomes the super admin in the platform tenant. You type the new username to confirm. |

`--reason` must be at least 10 characters.

## Bootstrap

`POST /api/auth/register` with `role: "SUPER_ADMIN"` creates the super admin only when
`ALLOW_SUPER_ADMIN_BOOTSTRAP=True`, `BOOTSTRAP_SUPER_ADMIN_KEY` is set and matches
(constant-time comparison), and no super admin exists. Keep `ALLOW_SUPER_ADMIN_BOOTSTRAP`
off; open it only to create the very first super admin, then switch it off and remove the key.

## Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `MFA_ENCRYPTION_KEYS` | (none) | Comma-separated Fernet keys, newest first, that encrypt TOTP secrets. Required for 2FA. Generate with `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`. Rotate by putting a new key first; keep the old one until no secret uses it (or reset 2FA). |
| `MFA_ISSUER` | `Maziwa Smart` | Name shown in the authenticator app. |
| `PLATFORM_ADMIN_PENDING_MFA_MINUTES` | `10` | Token lifetime before 2FA. |
| `PLATFORM_ADMIN_SESSION_MINUTES` | `30` | Token lifetime after 2FA. |
| `ALLOW_SUPER_ADMIN_BOOTSTRAP` | `False` | Opens the HTTP bootstrap (see above). |
| `BOOTSTRAP_SUPER_ADMIN_KEY` | (none) | The bootstrap key. Remove once a super admin exists. |
