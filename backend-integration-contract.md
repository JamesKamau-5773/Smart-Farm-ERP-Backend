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