# Feed Planning & Inventory: API Changes

**Status:** Implemented on branch `development`.
**Last updated:** 2026-11-03

Every change is backward compatible unless it's marked ⚠️. Endpoints that aren't mentioned here are unchanged.

---

## 1. Conventions

### 1.1 Error envelope (all feed, nutrition and inventory endpoints)
```json
{ "code": "MACHINE_READABLE_CODE", "error": "Human-readable message" }
```
- Every error response on these endpoints now includes a `code`. Branch on `code`, never on the `error` text.
- Where an endpoint doesn't set a specific code, one is derived from the HTTP status:

| HTTP | Default `code` |
|---|---|
| 400 | `VALIDATION_ERROR` |
| 401 | `UNAUTHENTICATED` |
| 403 | `FORBIDDEN` |
| 404 | `NOT_FOUND` |
| 409 | `CONFLICT` |
| 422 | `UNPROCESSABLE` |
| 500 | `INTERNAL_ERROR` |

- ⚠️ A 500 response no longer includes a `details` field. Internal error text is logged on the server only.

### 1.2 Dates
- "Mixed on" and "fed on" dates are **farm-local calendar dates** (setting `FARM_TIMEZONE`, default `Africa/Nairobi`).
- When `consumedOn` is left out, the farm's local "today" is used.
- **Frontend:** send the local date (`YYYY-MM-DD` built from the device's local time), not `new Date().toISOString().slice(0, 10)`, which gives the UTC date.
- ⚠️ A `consumedOn` later than the farm's today is rejected with `400`.
- `GET /api/auth/me` returns `farm_timezone` (IANA name, e.g. `"Africa/Nairobi"`). Build "today" in that zone rather than the device's.

### 1.3 Page access: new `feeding` key
| Key | Grants |
|---|---|
| `feed` | Feed planning: recipes, formulation, costs, batches, milk lab. **Includes `feeding`.** |
| `feeding` (new) | Daily feeding only: today's instructions, recording feed given, batch stock status. No prices, costs or recipe shares. |

- New farm-hand accounts default to `feeding` instead of `feed`. Existing staff keep what the owner saved.
- `feeding` is accepted wherever page access is edited (staff invite, provisioning, staff edit).

---

## 2. Feed planning

### `POST /api/v1/recipes/auto-save` — FIXED
- Previously this **always failed with a 500**. It now saves the mix, and assigns it to a group when `feeding_group` is sent.
- Optional measurement fields are now accepted:
  - `quantity_basis`: `total_ration` | `concentrate`
  - `concentrate_kg_per_head_day`
  - `bulk_density_kg_per_litre` and `bucket_volume_litres` (send both or neither)
  - `scoop_weight_kg`
- A dairy-meal mix defaults to `concentrate`.

`201`: unchanged shape (`recipe_id`, `recipe_name`, `status: "ADOPTED"`, …).

### `GET /api/v1/nutrition/herd/feeding-plan/by-group` — CHANGED (label text)
- `quantity_label` for a group **with no assigned mix** is now `"Total daily feed need (dry matter, all feeds)"`. This is whole-diet intake, not an amount of any one mix.
- With a mix assigned, it's `"Concentrate"` or `"Total ration (dry matter)"`.
- `requires_concentrate_rate: true` means: "set kg/head/day on the mix before these amounts can be used."

### `POST /api/v1/recipes/formulate` — CHANGED (additive)
A `422` (target protein can't be reached) may now include:
```json
"suspect_ingredients": [
  { "ingredient_id": 34, "name": "Sunflower Cake",
    "warnings": [{ "code": "PROTEIN_LIKELY_PERCENT", "field": "protein_grams_per_kg",
                   "value": 30, "suggested_value": 300, "message": "Sunflower Cake has 30 g/kg …" }] }
]
```
When it's present, show it ahead of `hint`. Bad ingredient data is the more likely cause.

### `GET /api/v1/nutrition/mixers/{dairy_meal|main_meal}/ingredients` — CHANGED (additive)
- Each ingredient has `data_warnings` (same shape as above). Archived items are excluded.

### `GET /api/v1/nutrition/feeding/today` — NEW (page `feeding`)
Cost-free instructions for the people doing the feeding.
```json
{
  "date": "2026-11-03",
  "groups": [{
    "feeding_group": "lactating", "headcount": 2,
    "mix_name": "Lactating Dairy Meal", "recipe_type": "dairy_meal",
    "quantity_basis": "concentrate", "quantity_label": "Concentrate",
    "feeding_times_per_day": 3,
    "daily_kg_per_head": 4.0, "kg_per_head_per_feeding": 1.33,
    "daily_group_batch_kg": 8.0, "group_batch_per_feeding_kg": 2.67,
    "physical_measures": { "kg_per_bucket": 6.0, "group_buckets_per_feeding": 0.44 },
    "requires_concentrate_rate": false,
    "active_batch_id": 41,
    "ready": true,
    "not_ready_reason": null,
    "not_ready_message": null
  }],
  "active_batches": [{ "batch_id": 41, "batch_name": "…", "recipe_type": "dairy_meal", "mixed_on": "2026-11-02",
                        "total_weight_kg": 25, "remaining_kg": 20.5, "daily_feeding_rate_kg": 4.5, "days_until_empty": 4.6 }],
  "totals": { "total_active_animals": 12, "total_daily_feed_kg": 87.6 }
}
```
- `ready` is `true` only when `not_ready_reason` is `null`. Otherwise `not_ready_reason` is the first of these that applies:

| `not_ready_reason` | Meaning |
|---|---|
| `NO_MIX` | No mix is assigned to the group. |
| `NO_ANIMALS` | The group has no animals. |
| `NO_CONCENTRATE_RATE` | The mix needs kg/head/day set before amounts can be used. |
| `NO_ACTIVE_BATCH` | No batch of the group's mix type is in store. |

  `not_ready_message` is display text for the reason. Show it for any code the app doesn't recognise.
- `recipe_type` is on every group. It is `null` only when the reason is `NO_MIX`.
- In `active_batches`, `recipe_type` is `null` for batches mixed before batches were linked to a recipe. Those batches never match a group.
- To record feeding, use the existing `POST /api/v1/nutrition/batches/{active_batch_id}/consumption-events`. It's now allowed for page `feeding`.

### `GET /api/v1/nutrition/batches/suggested-size?recipe_type=dairy_meal&days=7` — NEW (page `feed`)
```json
{ "recipe_type": "dairy_meal", "days": 7, "daily_demand_kg": 8.0, "in_store_kg": 20.5,
  "suggested_batch_kg": 40, "recipe_id": 12, "max_batch_kg": 50.0,
  "limiting_ingredient": { "inventory_item_id": 34, "name": "Maize Germ", "in_stock_kg": 30.0 },
  "groups": [{ "feeding_group": "lactating", "daily_kg": 8.0 }], "reason": null }
```
- The result is rounded up to 5 kg.
- If `suggested_batch_kg` is 0, show `reason` instead.
- `max_batch_kg` is the largest batch current stock allows at the shares saved on `recipe_id`, rounded down to 0.1 kg. `limiting_ingredient` is the item that runs out first.
- `recipe_id` is the mix of this type assigned to groups. If groups use different mixes of the same type, it's the one with the most daily demand.
- When no mix of this type is assigned, `recipe_id`, `max_batch_kg` and `limiting_ingredient` are `null`.
- When `suggested_batch_kg` is more than `max_batch_kg`, offer "Use maximum batch". The batch dialog's stock check still applies.
- `days` must be 1–60 (`400` otherwise).

### `PUT /api/v1/nutrition/feeding-groups/profiles/{group}` — CHANGED (additive)
- The response now includes the profile `id`.

---

## 3. Inventory

### `GET /api/inventory/items` — CHANGED
- Archived items are hidden by default. Add `?include_archived=true` to include them.
- Each item now has `is_active` and `data_warnings`.

### `POST /api/inventory/items` and `PATCH /api/inventory/items/{id}` — CHANGED
- **`sku` is optional.** The backend never required it, so the form shouldn't either.
- Impossible nutrient values are rejected with `400 VALIDATION_ERROR`:
  - protein outside 0–999.99 g/kg
  - energy outside 0–30 MJ/kg
  - fiber outside 0–999.99 g/kg
- ⚠️ `PATCH` can no longer change stock. A `currentStock`/`current_qty` value that **differs** from the stored value returns `400 STOCK_CHANGE_REQUIRES_MOVEMENT`. Sending the unchanged value is fine. Change stock through Restock, Use or Stock Count, so every change is recorded.

### `DELETE /api/inventory/items/{id}` — CHANGED
- If the item is used by recipes, batches or stock history, you get `409`:
```json
{ "code": "ITEM_IN_USE", "error": "… Archive it instead …", "can_archive": true }
```
  Offer **Archive** in that dialog.

### `POST /api/inventory/items/{id}/archive` and `.../restore` — NEW (owner)
- `200`: the item, with `is_active` false or true.
- Archived items keep their history, are hidden from lists and mixers, and can't be added to new mixes.

### `POST /api/inventory/items/{id}/data-fixes` — NEW (owner)
```json
{ "code": "PROTEIN_LIKELY_PERCENT" }
```
- Applies the correction the server computes for that warning (for example 30 → 300 g/kg).
- `200`: the updated item.
- `400`: the item has no such warning.

### `POST /api/inventory/movements` — CHANGED (additive)
Restock now accepts:

| Field | Meaning |
|---|---|
| `quantity` | Any positive amount (e.g. 23.5), not only whole bags |
| `unit_cost` | Price per kg paid for this delivery. Updates the item's cost per kg as a weighted average of stock on hand and this delivery. |
| `supplier_name` | Records the delivery as a supplier lot. Repeat deliveries from the same supplier on the same day go into one lot. |
| `record_expense` | `true` also posts a **Feed Purchase** expense to the ledger. Needs `unit_cost`. Leave it `false` if the farmer records purchases in the ledger by hand, or the purchase will be counted twice. |

`201` adds `ledgerEntryId` and `supplierLotId`. `movement.supplier_name` is included.

⚠️ Write-offs keep the reason they were recorded with: the movement's `reason_code` is `SPOILAGE`, `SPILL`, `EXPIRED`, `DAMAGE` or `SHRINKAGE`, no longer always `SHRINKAGE`. Stock-count losses are `AUDIT_LOSS` and gains `AUDIT_GAIN`. Write-offs recorded before this change stay `SHRINKAGE`, because their original reason wasn't saved.

These write-offs now post an **Inventory Write Off** expense automatically. Previously this path crashed. The response includes `ledgerEntryId`.

### `POST /api/inventory/items/{id}/audit` (stock count)
- Allowed for owners (`FARMER`) and every role with full farm access (`FARM_ADMIN`, `ADMIN`, `SUPER_ADMIN`). It's also allowed for staff whose page access includes `inventory`.

### Audit trail
These events are now written to the audit log with who did it, from which IP, and what changed:
- inventory item create, update, archive, restore and delete
- stock movements
- recipe save, update and delete
- feeding-group profile changes
- batch mixing
- feeding records
