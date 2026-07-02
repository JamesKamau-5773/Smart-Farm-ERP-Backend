# Backend Endpoint Map

This is the current backend contract for the frontend integration.

## Access Model

- Protected routes require `Authorization: Bearer <token>`.
- Role parity is enabled for elevated users: `FARMER`, `ADMIN`, and `SUPER_ADMIN` are treated as equivalent for endpoint authorization.
- Tenant and farm are read from JWT claims. Header override support exists for `X-Tenant-ID` and `X-Farm-ID`.

## Pagination And Filters

List endpoints now support pagination using:

- `page` (default `1`)
- `per_page` (default `20`, max `200`)

Where implemented, filtering supports `q` and route-specific keys such as `status`, `category`, `movement_type`, and `flag`.

## Auth

- `POST /api/auth/login`
- `POST /api/auth/register`
- `POST /api/auth/register` request body:
	- `farm_name` (required)
	- `phone_number` (required)
	- `password` (required, min 8 chars)
	- `username` (optional; defaults to `phone_number`)
	- `tenant_name` (optional)
	- `name` (optional)
	- `tenant_type` (`single` or `cooperative`, optional)
	- `role` (optional; defaults to `FARMER`)
- `POST /api/auth/switch-farm`
- `POST /api/auth/logout`
- `GET /api/auth/me`
- `GET /api/auth/status`

## HR

- `POST /api/hr/staff`
- `POST /api/hr/employees`
- `GET /api/hr/staff`
- `GET /api/hr/employees`
- `GET /api/hr/staff/<staff_id>`
- `GET /api/hr/employees/<staff_id>`
- `PATCH /api/hr/staff/<staff_id>`
- `PATCH /api/hr/employees/<staff_id>`
- `POST /api/hr/staff/<staff_id>/verify-return`
- `POST /api/hr/employees/<staff_id>/verify-return`
- `POST /api/hr/payroll`
- `POST /api/hr/payroll-records`
- `GET /api/hr/payroll`
- `GET /api/hr/payroll-records`
- `POST /api/hr/payroll/runs`
- `GET /api/hr/payroll/runs`
- `GET /api/hr/payroll/runs/<run_id>`

## Frontend-Critical Livestock/Operations Routes

- `GET /api/herd`
- `POST /api/herd`
- `GET /api/herd/<cow_id>`
- `PATCH /api/herd/<cow_id>`
- `DELETE /api/herd/<cow_id>`
- `GET /api/animals/<cow_id>`
- `PATCH /api/animals/<cow_id>`
- `GET /api/animals/<cow_id>/milk-history`
- `GET /api/animals/<cow_id>/events`
- `POST /api/animals/<cow_id>/events`
- `GET /api/production/milk-drop-alerts`
- `POST /api/production/milk-drop-alerts/<alert_id>/investigate`

## Frontend-Critical Clinical/Safety Routes

- `POST /api/clinical/cows/<cow_id>/medical`
- `POST /api/clinical/livestock/<cow_id>/medical`
- `PUT /api/clinical/cows/<cow_id>/hardlock`
- `PUT /api/clinical/livestock/<cow_id>/hardlock`
- `GET /api/safety/dashboard`
- `GET /api/veterinary/hardlocks/active`
- `GET /api/medical/records`
- `POST /api/medical/records`

## Other Operations Routes

- `POST /api/operations/cows/<cow_id>/milk`
- `POST /api/operations/livestock/<cow_id>/milk`
- `POST /api/operations/semen-inventory`
- `GET /api/operations/semen-inventory`
- `POST /api/operations/breeding-logs`
- `PUT /api/operations/breeding-logs/<log_id>/status`
- `GET /api/operations/breeding/performance`
- `GET /api/production/yield`
- `POST /api/production/yield`
- `GET /api/production/yield/<log_id>`
- `DELETE /api/production/yield/<log_id>`
- `GET /api/production/summary`
- `GET /api/breeding`
- `POST /api/breeding`
- `PATCH /api/breeding/<log_id>`
- `GET /api/lab/entries`
- `POST /api/lab/entries`
- `GET /api/clerk/entries`
- `POST /api/clerk/entries`

Legacy compatibility:

- Existing prefixed paths under `/api/operations/api/*` are still active for backward compatibility.

## Inventory

- `POST /api/v1/inventory/deduct`
- `GET /api/inventory/items`
- `POST /api/inventory/items`
- `PATCH /api/inventory/items/<item_id>`
- `DELETE /api/inventory/items/<item_id>`
- `GET /api/inventory/movements`
- `POST /api/inventory/movements`
- `GET /api/inventory/stock`

## Finance

- `GET /api/finance/unit-cost`
- `GET /api/finance/customers`
- `POST /api/finance/customers`
- `GET /api/finance/customers/<customer_id>`
- `GET /api/finance/ledger`
- `POST /api/finance/ledger`
- `GET /api/finance/buyers`
- `POST /api/finance/buyers`
- `GET /api/finance/buyers/<buyer_id>`
- `PATCH /api/finance/buyers/<buyer_id>`
- `GET /api/finance/statements/<token>`
- `POST /api/finance/billing/stk-push`
- `POST /api/finance/mpesa/callback`

## Dashboard

- `GET /api/v1/dashboard/summary`
- `GET /api/production/summary`

## Breeding Alias

- `PATCH /api/v1/breeding/insemination/<log_id>/outcome`

## Nutrition And Feed

- `POST /api/v1/feed/calculate-schedule`
- `POST /api/v1/nutrition/batches`
- `POST /api/v1/nutrition/batches/<batch_id>/consumption-events`
- `GET /api/v1/nutrition/analytics/feed-cost-efficiency`
- `GET /api/v1/nutrition/analytics/active-batch-roi-trend-weekly`
- `GET /api/v1/nutrition/dashboard`
- `GET /api/nutrition/dashboard`
- `GET /api/v1/nutrition/recipes`
- `POST /api/v1/nutrition/recipes`
- `PATCH /api/v1/nutrition/recipes/<recipe_id>`
- `DELETE /api/v1/nutrition/recipes/<recipe_id>`
- `GET /api/feed/recipes`
- `POST /api/feed/recipes`
- `PATCH /api/feed/recipes/<recipe_id>`
- `DELETE /api/feed/recipes/<recipe_id>`
- `POST /api/v1/nutrition/feed/formulate`
- `POST /api/feed/formulate`
- `GET /api/v1/nutrition/units/conversions`
- `POST /api/v1/nutrition/units/conversions`
- `GET /api/units/conversions`
- `POST /api/units/conversions`
- `GET /api/v1/nutrition/feed/costing`
- `GET /api/feed/costing`

## Tenant, Export, Tasking

- `GET /api/tenant/profile`
- `POST /api/tenant/cooperatives`
- `POST /api/tenant/cooperatives/<cooperative_id>/members`
- `POST /api/tenant/cooperatives/<cooperative_id>/members/bulk`
- `GET /api/v1/export/animal/<animal_id>/pdf`
- `POST /api/v1/tasks/<routine_id>/complete`
- `GET /api/routine/plans`
- `POST /api/routine/plans`
