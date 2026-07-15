# Backend Endpoint Map

This is the current backend contract for the frontend integration.

## Access Model

- Protected routes require `Authorization: Bearer <token>`.
- Elevated access policy: `FARMER`, `ADMIN`, and `SUPER_ADMIN` have full endpoint access across protected routes.
- Tenant and farm are read from JWT claims. The backend does not rely on `X-Tenant-ID` or `X-Farm-ID` headers for request scoping.

## Mutation Semantics

- `400` means the request body is missing required fields or contains malformed values.
- `404` means a referenced tenant-scoped record does not exist.
- `409` means the create or update hits a tenant-scoped uniqueness conflict.
- Frontend create flows should treat `409` as a business conflict and allow the user to retry with new data.

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
- `GET /api/production/history/<cow_id>`
- `GET /api/animals/<cow_id>/events`
- `POST /api/animals/<cow_id>/events`
- `GET /api/production/milk-drop-alerts`
- `POST /api/production/milk-drop-alerts/<alert_id>/investigate`

`POST /api/herd` accepts `tag_number` and `date_of_birth` as the canonical fields. For frontend compatibility, the backend also accepts `id`/`tag`/`tagNumber` for the tag and `dob`/`dateOfBirth` for the birth date.

### Herd create schema

Request body:

```json
{
	"tag_number": "C-002",
	"name": "Ruby",
	"breed_status": "Foundation",
	"date_of_birth": "2026-07-01"
}
```

Frontend aliases accepted by the backend:

- `id`, `tag`, `tagNumber` -> `tag_number`
- `dob`, `dateOfBirth` -> `date_of_birth`

Response body:

```json
{
	"id": 7,
	"tag": "C-002",
	"tag_number": "C-002",
	"name": "Ruby",
	"dob": "2026-07-01",
	"date_of_birth": "2026-07-01",
	"current_status": "Lactating"
}
```

Conflict behavior:

- `409` when `tag_number` already exists for the tenant
- `400` when `tag_number` or `date_of_birth` is missing/invalid

The browser payload `{ id, name, breed, dob, hasCalved }` is accepted because `id` maps to `tag_number` and `dob` maps to `date_of_birth`. `breed` is treated as an alias for `breed_status`; if omitted, the backend defaults to `Foundation`.

### Animal milk history schema

`GET /api/animals/<cow_id>/milk-history` and `GET /api/production/history/<cow_id>` return the same animal-scoped payload.

Response body:

```json
{
	"animal": {
		"id": 7,
		"tag_number": "C-002",
		"name": "Ruby",
		"breed": "Foundation",
		"breed_status": "Foundation",
		"date_of_birth": "2026-07-01",
		"current_status": "Lactating",
		"is_active": true
	},
	"sessions": [
		{
			"id": 44,
			"cow_id": 7,
			"amount": 16.5,
			"session": "Morning",
			"milkingDate": "2026-07-03",
			"status": "RECORDED",
			"milker": 3,
			"timestamp": "2026-07-03T05:32:10+00:00"
		}
	],
	"meta": {
		"page": 1,
		"per_page": 20,
		"total": 1,
		"pages": 1
	}
}
```

Volume field convention:

- API responses use `amount` as the canonical milk-volume field.

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
- `PATCH /api/production/yield/<log_id>`
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

### Inventory item create schema

Request body:

```json
{
	"name": "hay",
	"sku": "h-001",
	"category": "Bulk Feed",
	"unit": "KG",
	"currentStock": 164,
	"reorderLevel": 10,
	"energy_mj_per_kg": 0,
	"protein_grams_per_kg": 0,
	"fiber_grams_per_kg": 0,
	"cost_per_kg": 0
}
```

Accepted aliases:

- `current_qty` -> `currentStock`
- `minimum_threshold` -> `reorderLevel`

Response body:

```json
{
	"id": 1,
	"name": "hay",
	"sku": "h-001",
	"category": "Bulk Feed",
	"unit": "KG",
	"reorderLevel": 10.0,
	"currentStock": 164.0
}
```

Conflict behavior:

- `409` when `name` or `sku` already exists for the tenant
- `400` when `name`, `category`, or `unit` is missing

Frontend should treat `409` as a duplicate-item conflict, not a transport failure.

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

### Finance create schemas

Buyer create request:

```json
{
	"name": "Kisii Dairy",
	"agreed_rate_per_liter": 55,
	"is_active": true
}
```

Buyer response:

```json
{
	"id": 3,
	"name": "Kisii Dairy"
}
```

Conflict behavior:

- `409` when buyer name already exists for the tenant

Customer create request:

```json
{
	"name": "Mary",
	"phone_number": "254712345678",
	"account_balance": 0,
	"daily_contract_liters": 0,
	"is_active": true
}
```

Customer response:

```json
{
	"id": 5,
	"name": "Mary",
	"phone_number": "254712345678",
	"account_balance": 0.0,
	"daily_contract_liters": 0.0,
	"is_active": true
}
```

Conflict behavior:

- `409` when phone number already exists for the tenant

Ledger entry create request:

```json
{
	"transaction_type": "Expense",
	"category": "Feed Purchase",
	"amount": 1000,
	"reference_code": "REF-123",
	"description": "Morning feed",
	"customer_id": null
}
```

## Dashboard

- `GET /api/v1/dashboard/summary`
- `GET /api/production/summary`

Dashboard tenant scope behavior:

- `/api/v1/dashboard/summary` and `/api/production/summary` resolve tenant scope from JWT request context.
- Optional compatibility check: `X-Tenant-ID` can be supplied and must match the authenticated tenant.
- The client does not need to pass `tenant_id` as a query parameter.

## Breeding Alias

- `PATCH /api/v1/breeding/insemination/<log_id>/outcome`

### Production yield create and edit schema

Yield create request:

```json
{
	"cow_id": 7,
	"amount": 18.0,
	"session": "Morning"
}
```

Yield create response:

```json
{
	"id": 55,
	"cow_id": 7,
	"cow_name": "Ruby",
	"amount": 18.0,
	"session": "Morning",
	"milkingDate": "2026-07-03",
	"status": "RECORDED"
}
```

Yield edit request (`PATCH /api/production/yield/<log_id>`):

```json
{
	"amount": 17.5,
	"session": "Evening",
	"milkingDate": "2026-07-03T16:30:00+00:00"
}
```

Yield detail response (`GET /api/production/yield/<log_id>`) includes:

- `cow_id`
- `cow_name`
- `breed`
- `average`
- `peak`
- `sessions` (animal session history)

## Nutrition And Feed

### Feed Schedule & Per-Cow Yield Targets (NEW)

- `POST /api/v1/feed/calculate-schedule` - Legacy herd-level calculation
- `POST /api/v1/animals/<cow_id>/yield-target` - Set/update cow milk target
- `GET /api/v1/animals/<cow_id>/yield-target` - Get cow milk target
- `PATCH /api/v1/animals/<cow_id>/yield-target` - Update cow target fields
- `DELETE /api/v1/animals/<cow_id>/yield-target` - Deactivate cow target
- `GET /api/v1/herd/yield-targets` - List all active yield targets
- `GET /api/v1/herd/feeding-plan/from-targets` - Calculate plan from saved targets (LACTATING cows only)
- `POST /api/v1/herd/feeding-plan/custom` - Calculate plan from custom cow targets

### Nutrition & Feed Batch Management

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

### Per-Cow Yield Target Endpoints (NEW)

#### POST /api/v1/animals/<cow_id>/yield-target
Set or update milk production target for a specific cow.

Request body:
```json
{
  "target_liters": 2.5,
  "base_herd_feed_kg": 0.5,
  "times_to_feed_daily": 2
}
```

Response (201 Created or 200 OK):
```json
{
  "id": 12,
  "cow_id": 5,
  "cow_tag": "C-001",
  "target_liters": 2.5,
  "base_herd_feed_kg": 0.5,
  "times_to_feed_daily": 2,
  "status": "Active",
  "action": "created"
}
```

Error behavior:
- `400` when `target_liters` is missing or invalid
- `400` when `times_to_feed_daily` not in {2, 3, 4}
- `400` when cow is not LACTATING or DRY status
- `400` when cow is inactive

#### GET /api/v1/animals/<cow_id>/yield-target
Retrieve yield target for a specific cow.

Response (200 OK):
```json
{
  "id": 12,
  "cow_id": 5,
  "cow_tag": "C-001",
  "cow_name": "Bessie",
  "cow_status": "Lactating",
  "target_liters": 2.5,
  "base_herd_feed_kg": 0.5,
  "times_to_feed_daily": 2,
  "status": "Active"
}
```

Error behavior:
- `404` when no yield target exists for cow

#### GET /api/v1/herd/yield-targets
List all active yield targets for the herd.

Response (200 OK):
```json
{
  "count": 3,
  "targets": [
    {
      "id": 12,
      "cow_id": 5,
      "cow_tag": "C-001",
      "cow_name": "Bessie",
      "cow_status": "Lactating",
      "target_liters": 2.5,
      "base_herd_feed_kg": 0.5,
      "times_to_feed_daily": 2,
      "status": "Active"
    }
  ]
}
```

#### PATCH /api/v1/animals/<cow_id>/yield-target
Update specific fields of a yield target (partial update).

Request body (any combination):
```json
{
  "target_liters": 3.0,
  "times_to_feed_daily": 3
}
```

Response (200 OK): Same as POST response

Error behavior:
- `400` for invalid field values
- `404` when target doesn't exist

#### DELETE /api/v1/animals/<cow_id>/yield-target
Deactivate a yield target (soft delete).

Response (200 OK):
```json
{
  "id": 12,
  "cow_id": 5,
  "cow_tag": "C-001",
  "status": "Inactive",
  "message": "Yield target for C-001 deactivated."
}
```

Error behavior:
- `404` when target doesn't exist

### Herd Feeding Plan Endpoints (NEW)

#### GET /api/v1/herd/feeding-plan/from-targets?milking_frequency=2
Calculate herd feeding plan from saved yield targets (LACTATING cows only).

Query parameters:
- `milking_frequency` (optional): Override recommended frequency with 2, 3, or 4

Response (200 OK):
```json
{
  "herd_total_target_liters": 6.3,
  "total_meal_needed_kg": 1.2,
  "total_milking_topup_kg": 0.5,
  "per_milking_session_kg": 0.25,
  "suggested_yard_feedings": 2,
  "used_milking_frequency": 2,
  "farmer_reasoning": "Standard layout. 2 daily feedings.",
  "cow_breakdown": [
    {
      "cow_id": 5,
      "cow_tag": "C-001",
      "cow_name": "Bessie",
      "target_liters": 2.5,
      "feed_allocation_kg": 0.48,
      "topup_per_session_kg": 0.12,
      "times_to_feed": 2
    }
  ],
  "active_lactating_count": 3,
  "dry_or_inactive_count": 1,
  "total_herd_count": 4
}
```

Error behavior:
- `400` when no active yield targets exist for lactating cows

#### POST /api/v1/herd/feeding-plan/custom
Calculate herd feeding plan from manually provided cow targets.

Request body:
```json
{
  "cow_targets": [
    {"cow_id": 1, "target_liters": 2.5},
    {"cow_id": 2, "target_liters": 2.0}
  ],
  "baseline_herd_meal_kg": 4.0,
  "milking_frequency": null
}
```

Response (200 OK): Same structure as `/from-targets`

Error behavior:
- `400` when `cow_targets` is empty
- `400` when any target lacks `cow_id` or `target_liters`
- `400` when `target_liters` is not > 0

### Nutrition create schemas

Recipe create request:

```json
{
	"name": "Winter Mix",
	"target_protein_percentage": 18,
	"is_active": true,
	"ingredients": [
		{
			"inventory_item_id": 1,
			"inclusion_percentage": 100
		}
	]
}
```

Conflict / validation behavior:

- `404` when an ingredient `inventory_item_id` does not exist for the tenant
- `409` when the recipe insert hits a tenant-scoped uniqueness conflict

Unit conversion create request:

```json
{
	"item_id": 1,
	"unit_name": "Bag",
	"kg_equivalent": 50
}
```

Conflict behavior:

- `409` when the unit conversion already exists for the tenant

Batch create request:

```json
{
	"batchName": "June Feed Mix A",
	"formulaId": null,
	"isSavedAsTemplate": false,
	"formulaName": "June Feed Mix A",
	"totalWeight": 100,
	"totalCost": 6200,
	"costPerKg": 62,
	"ingredients": [
		{
			"ingredientId": 1,
			"weight": 60,
			"percentage": 60,
			"lockedCostPerKg": 55
		}
	]
}
```

Validation behavior:

- `400` for malformed totals or ingredient data
- `404` when `formulaId` or ingredient references are invalid for the tenant
- `409` when a tenant-scoped uniqueness violation occurs during save

## Tenant, Export, Tasking

- `GET /api/tenant/profile`
- `POST /api/tenant/cooperatives`
- `POST /api/tenant/cooperatives/<cooperative_id>/members`
- `POST /api/tenant/cooperatives/<cooperative_id>/members/bulk`
- `GET /api/v1/export/animal/<animal_id>/pdf`
- `POST /api/v1/tasks/<routine_id>/complete`
- `GET /api/routine/plans`
- `POST /api/routine/plans`
