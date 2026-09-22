# Backend Integration Contract

This repository treats the entire `jivu-frontend` application as backend-linked product UI. The backend is not a feature slice target; it is the source of truth for the full build: auth, tenant/farm isolation, dashboard telemetry, operations, nutrition, finance, inventory, external customer views, staff, payroll, leave, verification, and audit workflows.

## Frontend Transport Contract

The shared HTTP client sends:

- `Authorization: Bearer <token>` from `sessionStorage.jivu_user`
- `X-Tenant-ID` from `tenantRef.tenantId`
- `X-Farm-ID` from `tenantRef.farmId`

The backend must accept those headers on every protected request and enforce tenant/farm isolation server-side.

The frontend uses React Query for server state and an offline queue for deferred writes, so the backend must provide stable, replay-safe endpoints for mutations that may be retried.

## Build-Wide Backend Surface

The routed frontend currently depends on backend support for these application areas:

- authentication and session bootstrap
- dashboard summaries and operational KPIs
- production logging, milk trends, and milk history
- herd registry, herd detail, and animal records
- breeding workflows and herd management actions
- milk lab and clerking utilities
- nutrition dashboards, feed formulation, and unit conversion support
- inventory registry and supply movements
- finance ledger, buyers, customer profiles, and statement views
- safety and medical/compliance dashboards
- staff registry and payroll
- customer portal statement access via tokenized public links

Each area should have a predictable resource model, server validation, and stable response shapes so the UI can remain thin and orchestration-focused.

## Core Domain Areas

### 1. Staff Registry

The backend must own the canonical staff record and return these fields at minimum:

- `id`
- `name`
- `role`
- `status` with values `ACTIVE`, `ON_LEAVE`, `OVERDUE`, `INACTIVE`
- `baseSalary`
- `loanBalance`
- `monthlyDeduction`
- `leaveType`
- `leaveStartDate`
- `leaveEndDate` or `expectedReturnDate`
- `actualReturnDate`
- `unpaidLeaveDaysThisMonth`
- `medicalCertifications`
- `medicalNotes`
- `returnVerifiedAt`
- `returnVerificationDecision`
- `returnVerificationNote`

### 2. Verification Workflow

The frontend expects overdue employees to be verified through a dedicated action, not a generic profile update.

Required backend behavior:

- accept a verify-return mutation for a specific staff member
- record whether the person returned
- record the note entered by the operator
- transition `OVERDUE -> ACTIVE` when the employee returned
- keep or restore `OVERDUE` when the employee did not return
- timestamp and audit the decision

### 3. Payroll Workflow

Payroll must be server-calculated or server-confirmed.

The backend should return:

- approved leave days
- overdue penalty days
- leave deduction
- advance deduction
- gross pay
- net pay
- payroll run metadata

The frontend can display the breakdown, but the backend must be the source of truth for the calculation.

## Module Contracts Beyond HR

### Dashboard

The dashboard needs aggregate summaries across the active farm and tenant, including production, finance, and operational signal cards. The backend should expose a single summary endpoint plus narrow endpoints for any drill-down widgets.

### Operations

Production, herd, breeding, lab, milk history, safety, records, and routine planning all depend on read/write endpoints that are scoped by farm and date range. The backend should support list, detail, create, update, and delete flows where the UI exposes them.

### Nutrition

Feed dashboards and formulation screens need recipe, ingredient, unit, and profitability data. The backend should provide deterministic conversion and cost inputs so the UI does not invent calculations locally.

#### Group Planning UI Contract

The group planning UI uses three nutrition endpoints with strict request and response shapes.

1. GET /api/v1/nutrition/feeding-groups/profiles

Response 200:

```json
{
  "tenant_id": 1,
  "profiles": [
    {
      "feeding_group": "lactating",
      "avg_body_weight_kg": 500.0,
      "dmi_percent_bw": 3.0,
      "target_protein_percent": 16.5,
      "feeding_times_per_day": 3,
      "is_default": true
    },
    {
      "feeding_group": "dry",
      "avg_body_weight_kg": 480.0,
      "dmi_percent_bw": 2.0,
      "target_protein_percent": 12.0,
      "feeding_times_per_day": 2,
      "is_default": true
    }
  ],
  "count": 5
}
```

2. PUT /api/v1/nutrition/feeding-groups/profiles/{feeding_group}

Path parameter:

- feeding_group enum: lactating, dry, calf_0_3m, calf_3_6m, heifer

Request body:

```json
{
  "avg_body_weight_kg": 600,
  "dmi_percent_bw": 3.0,
  "target_protein_percent": 13.5,
  "feeding_times_per_day": 3
}
```

Validation rules:

- avg_body_weight_kg: required, numeric, greater than 0
- dmi_percent_bw: required, numeric, greater than 0 and less than or equal to 10
- target_protein_percent: required, numeric, greater than 0 and less than or equal to 100
- feeding_times_per_day: required, integer-like numeric, greater than 0 and less than or equal to 12

Success response 200:

```json
{
  "feeding_group": "dry",
  "avg_body_weight_kg": 600.0,
  "dmi_percent_bw": 3.0,
  "target_protein_percent": 13.5,
  "feeding_times_per_day": 3,
  "message": "Profile saved."
}
```

Error response 400:

```json
{
  "error": "dmi_percent_bw must be > 0 and <= 10."
}
```

3. GET /api/v1/nutrition/herd/feeding-plan/by-group

Response 200:

```json
{
  "generated_on": "2026-08-25",
  "tenant_id": 1,
  "groups": [
    {
      "feeding_group": "lactating",
      "headcount": 20,
      "avg_body_weight_kg": 500.0,
      "dmi_percent_bw": 3.0,
      "target_protein_percent": 16.5,
      "feeding_times_per_day": 3,
      "daily_feed_per_head_kg": 15.0,
      "daily_group_feed_kg": 300.0,
      "daily_group_protein_kg": 49.5,
      "profile_source": "custom"
    },
    {
      "feeding_group": "dry",
      "headcount": 12,
      "avg_body_weight_kg": 480.0,
      "dmi_percent_bw": 2.0,
      "target_protein_percent": 12.0,
      "feeding_times_per_day": 2,
      "quantity_basis": "total_ration",
      "quantity_label": "Total ration (dry matter)",
      "total_ration_kg_per_head_day": 9.6,
      "daily_kg_per_head": 9.6,
      "kg_per_head_per_feeding": 4.8,
      "daily_group_batch_kg": 115.2,
      "group_batch_per_feeding_kg": 57.6,
      "daily_feed_per_head_kg": 9.6,
      "daily_group_feed_kg": 115.2,
      "daily_group_protein_kg": 13.82,
      "profile_source": "default",
      "assigned_recipe": {
        "id": 14,
        "name": "Dry Cow Total Ration",
        "recipe_type": "main_meal",
        "quantity_basis": "total_ration",
        "ingredients": [
          {
            "inventory_item_id": 8,
            "name": "Hay",
            "percentage": 60.0,
            "daily_group_kg": 69.12,
            "group_kg_per_feeding": 34.56
          }
        ]
      },
      "physical_measures": {
        "bulk_density_kg_per_litre": 0.4,
        "bucket_volume_litres": 20.0,
        "kg_per_bucket": 8.0,
        "daily_group_buckets": 14.4,
        "group_buckets_per_feeding": 7.2,
        "kg_per_scoop": 2.0,
        "daily_group_scoops": 57.6,
        "group_scoops_per_feeding": 28.8
      },
      "requires_concentrate_rate": false
    }
  ],
  "totals": {
    "total_active_animals": 87,
    "total_daily_feed_kg": 1260.4,
    "total_planned_mix_kg": 1260.4,
    "total_daily_protein_kg": 188.51
  }
}
```

Notes for frontend implementation:

- profile_source is default when no custom profile exists for that group.
- feeding_group values are stable enums and should be represented as union types in frontend models.
- values are rounded by backend for presentation-safe UI rendering.
- quantity_basis is `total_ration` or `concentrate`; the frontend must always show quantity_label beside amounts.
- concentrate recipes require `concentrate_kg_per_head_day`. If missing, planned mix quantities are zero and `requires_concentrate_rate` is true; never substitute total-ration DMI.
- ingredient kilograms are scaled from the assigned recipe percentages and the authoritative group batch.
- physical_measures is null until calibration exists. Bucket conversion requires both `bulk_density_kg_per_litre` and `bucket_volume_litres`; scoop conversion requires `scoop_weight_kg`.
- kilograms are authoritative. Bucket and scoop values are operational equivalents, not independent quantities.

4. PATCH /api/feed/recipes/{recipe_id}

Recipe allocation and physical-measure settings:

```json
{
  "quantity_basis": "concentrate",
  "concentrate_kg_per_head_day": 2.5,
  "bulk_density_kg_per_litre": 0.55,
  "bucket_volume_litres": 20,
  "scoop_weight_kg": 1.25
}
```

All numeric calibration values must be positive. Bulk density and bucket volume must be supplied together. Send null to clear an optional calibration.

### Inventory and Finance

Inventory, buyers, ledger, and customer profile screens depend on transaction histories, balances, and statement data. The backend should support paging, filtering, and tokenized statement access where the external portal needs it.

### External Portal

The customer portal uses a public/shared token route. The backend must validate the token, restrict the response to the correct statement scope, and keep the payload read-only.

## Suggested API Shape

### Staff

`GET /api/hr/staff`

Returns the full staff collection for the active tenant and farm.

`GET /api/hr/staff/:id`

Returns one staff record plus audit-relevant leave and verification fields.

`POST /api/hr/staff`

Creates a staff record.

`POST /api/onboarding/invite`

Creates or reissues a 48-hour login invitation for an existing staff record. The request includes `employee_id` and a role of `FARM_ADMIN`, `FARM_MANAGER`, `FARM_SUPERVISOR`, `FARM_HAND`, or `VETERINARY_DOCTOR`. Platform roles cannot be assigned. The response includes `claim_url`, `expires_in_hours`, and `onboarding_status`. Reissuing invalidates every earlier token. The account remains inactive until claimed through `POST /api/auth/claim-account`.

`POST /api/onboarding/provision`

Creates an active employee-linked account immediately from `employee_id`, `role`, and a temporary `password`. The password is hashed and never returned. The response sets `requires_password_reset: true` and the employee state to `PASSWORD_RESET_REQUIRED`.

`POST /api/auth/change-password`

Completes a required password reset using matching `password` and `confirm_password` fields. The temporary password cannot be reused. Success revokes the current restricted token, returns a new unrestricted token, and moves the employee state to `ACTIVE`.

While `requires_password_reset` is true, the backend rejects protected routes with `403` and code `PASSWORD_RESET_REQUIRED`. Login, account identity, password change, and logout remain available. React Router should use the login or `/api/auth/me` flag for navigation, but the backend remains authoritative.

Legacy `POST /api/hr/staff/:id/account-invite` remains available as an alias.

The employee record and login account are separate but linked: all workers can be represented in HR/payroll, while only workers who need application access require an account.

`GET /api/hr/staffing-recommendations`

Returns advisory role counts based on the tenant's active employee count. Recommendations never create accounts or grant permissions automatically. Current bands are: up to 5 employees (`SMALL`), 6-15 (`GROWING`), 16-30 (`ESTABLISHED`), and above 30 (`LARGE`).

`PATCH /api/hr/staff/:id`

Updates profile, finance, and leave fields that are not part of a verification action.

### Verify Return

`POST /api/hr/staff/:id/verify-return`

Request:

```json
{
  "returned": true,
  "note": "Employee reported back to duty"
}
```

Response:

```json
{
  "id": "staff_123",
  "status": "ACTIVE",
  "actualReturnDate": "2026-07-01",
  "returnVerifiedAt": "2026-07-01T10:15:00.000Z",
  "returnVerificationDecision": "YES",
  "returnVerificationNote": "Employee reported back to duty"
}
```

### Payroll

`POST /api/hr/payroll/runs`

Returns a payroll run with line items for every staff member.

The line items should include the leave split so the frontend can render approved leave versus overdue penalty days without recomputing them locally.

### Dashboard and Operations

The frontend already expects endpoints such as:

- `/api/production/summary`
- `/api/v1/dashboard/summary`
- `/api/finance/unit-cost`

The backend may map those paths differently, but it must provide equivalent farm-scoped summaries and keep the shapes stable.

For a route-by-route breakdown, see backend-endpoint-map.md.

If the backend prefers the exact route inventory already supplied by the server team, the frontend can treat singular/plural resource names as aliases as long as the response shapes stay identical.

## Backend Rules the Frontend Depends On

- `ACTIVE` is the default working state.
- `ON_LEAVE` means an approved leave state with start and return dates.
- `OVERDUE` means the employee has not returned by the expected return date and requires verification.
- Headcount recommendations are advisory; access is assigned explicitly according to responsibility.
- Managers inherit supervisor and farmhand operational access. Supervisors inherit farmhand operational access.
- Verification is a separate workflow from profile edits.
- Payroll deduction logic must be deterministic and auditable.
- All mutations should return structured errors with validation messages.
- Changes should be idempotent or safely retryable where possible.

## Enterprise Grade Criteria

The build becomes enterprise grade when the backend provides:

- authoritative state transitions
- audit logging for leave, verification, and payroll actions
- multi-tenant isolation using the headers above
- server-side validation and calculation
- stable response shapes for registry, drawer, verification, and payroll screens
- role-aware access control for HR and finance operations
- module-level authorization for operations, finance, inventory, nutrition, and external portal access
- retry-safe mutation handling for offline queue replay
