# Period Totals API — contract v1

The backend computes every ledger and production total. The frontend never sums,
buckets or converts.

## Conventions

| Thing | Format | Example |
|---|---|---|
| Money | integer minor units (cents), as a string | `"2700500"` = KES 27,005.00 |
| Litres | decimal string, 1 dp | `"246.0"` |
| Percent | decimal string, 1 dp, or `null` when the previous value is 0 | `"-5.3"` |
| Dates | farm-local (`FARM_TIMEZONE`, default `Africa/Nairobi`) `YYYY-MM-DD` | `"2026-11-06"` |
| Weeks | ISO weeks, Monday start, ISO week-year | `"2026-W45"` |

Bucket keys: year `2026`, month `2026-11`, week `2026-W45`, day `2026-11-06`.

**Scope.** Every endpoint is scoped by the JWT only. Ledger: `tenant_id`, plus `farm_id` when the token
carries one (same rule as `GET /api/finance/ledger`). Production: `tenant_id` (the `milk_logs` table has no
`farm_id` yet).

**Filters.** Each endpoint takes the same filters as its list endpoint, parsed by one shared schema and
applied by one shared query builder, so the list, its KPI cards and these totals cannot disagree.

| List | Filters |
|---|---|
| Ledger (`GET /api/finance/ledger`) | `type` (`income`, `expense`, `unpaid`, `credit`, or an entry type: `revenue`, `payment`, `debit`, …), `category` (e.g. `Feed Purchase`; matches the category or the payment's income category), `search` (customer/buyer name, typo-tolerant), `account_type` + `account_id`, `date_from`, `date_to` (`start_date`/`end_date` still accepted) |
| Production (`GET /api/production/yield`) | `status` (`VERIFIED`, `RECORDED`, `FLAGGED`, `ISOLATED`, case-insensitive, matching each row's `status`; `anomaly` still selects anything the anomaly check flagged; other values → `400 VALIDATION_ERROR` with `fields.status = "invalid"`), `session` (`Morning`/`Midday`/`Evening`, case-insensitive), `search` (cow tag or name), `date_from`, `date_to` |

Date filters are inclusive farm-local dates and are intersected with the requested period.

## Ledger classification (one rule set)

Defined once in `app/services/ledger_classification.py`. Used by the ledger KPI cards, the summary,
the group totals and the dashboard's daily revenue/costs.

- Only **POSTED** entries are totalled. DRAFT and VOIDED entries are still listed and counted in `count`.
- `income` = Revenue + Payment (cash basis: money that came in)
- `expenses` = Expense
- `unpaid` = Debit (charged to a customer account, not yet received). **Never inside income.**
- `credit` = Credit (credit notes / price reductions). **Never inside income.**
- `net` = income − expenses
- The entry type sets the direction, not the stored sign: amounts are summed as `ABS(amount)`.
- `count` = number of entries matching the filters (all statuses), the same as the list's `meta.total`.

## 1) `GET /api/ledger/summary?period=week|month|year&anchor=YYYY-MM-DD&<filters>`

Also served at `/api/finance/ledger/summary`. `period` defaults to `month`, `anchor` to the farm's today.

```json
{
  "period": "month", "key": "2026-11", "label": "Nov 2026",
  "range": { "from": "2026-11-01", "to": "2026-11-30" },
  "has_next": false,
  "current":  { "income": "159500", "expenses": "50000", "net": "109500",
                "unpaid": "40000", "credit": "5000", "count": 9 },
  "previous": { "key": "2026-10", "label": "Oct 2026", "income": "80000", "expenses": "10000",
                "net": "70000", "unpaid": "0", "credit": "0", "count": 2 },
  "change":   { "net_abs": "39500", "net_pct": "56.4" },
  "breakdown": [ { "key": "2026-W44", "label": "26 Oct – 1 Nov", "income": "2500",
                   "expenses": "0", "net": "2500" } ]
}
```

- `has_next`: whether the next period has started (its first day ≤ farm today).
- `change.net_pct` = (current.net − previous.net) / |previous.net| × 100; `null` when previous.net is 0.
- Breakdown granularity: `year` → months, `month` → ISO weeks, `week` → days. Every bucket in the range is
  listed, including empty ones (zeros). Edge weeks keep their full ISO-week label, but their totals cover
  only the days inside the period.
- `credit` is an addition to the v1 draft, so credit can be shown next to unpaid.

## 2) `GET /api/production/summary?period=week|month|year&anchor=YYYY-MM-DD&<filters>`

Without `period`, this path still returns the legacy "today" dashboard payload, unchanged.

```json
{
  "period": "month", "key": "2026-11", "label": "Nov 2026",
  "range": { "from": "2026-11-01", "to": "2026-11-30" }, "has_next": false,
  "current":  { "litres": "35.5", "entries": 4, "milking_days": 2,
                "avg_litres_per_day": "17.8", "avg_litres_per_cow_day": "11.8",
                "fed_to_calves_litres": "3.0", "available_litres": "32.5",
                "last_entry_date": "2026-11-08" },
  "previous": { "key": "2026-10", "label": "Oct 2026", "litres": "20.0",
                "fed_to_calves_litres": "2.0", "available_litres": "18.0", "...": "..." },
  "change":   { "litres_abs": "15.5", "litres_pct": "77.5",
                "avg_litres_per_day_pct": "-11.3", "entries_pct": "300.0",
                "fed_to_calves_pct": "50.0", "available_pct": "80.6" },
  "breakdown": [ { "key": "2026-11-01", "label": "Sun 1", "litres": "0.0" } ]
}
```

- `milking_days` = distinct farm-local days with at least one entry.
- `avg_litres_per_day` = litres / milking_days; `avg_litres_per_cow_day` = litres / distinct (cow, day) pairs.
  Both are `"0.0"` when there are no entries.
- Breakdown granularity: `year` → months, `month` → days, `week` → days.
- `fed_to_calves_litres` = calf feedings (`milk_dispositions`, type `CALF_FEED`) dated in the period.
  `available_litres` = `litres` − `fed_to_calves_litres`. Both appear in `current` and `previous`.
  Calf feedings aren't linked to a cow's milking or a session, so when `session`, `search` or
  `status=anomaly` is set, both are `null` (as are their `_pct` changes) instead of a wrong number.
- `current.last_entry_date` = farm-local date of the newest milk entry matching the filters, ignoring the
  period and any date filters; `null` when there are none. It is not repeated in `previous`.
- Every `_pct` in `change` is `null` when the previous value is 0 or either value is `null`
  (e.g. `avg_litres_per_day_pct` when either period has no entries).

## 3) Group totals

```
GET /api/ledger/group-totals?levels=year,month,week,day&<filters>      (also /api/finance/ledger/group-totals)
GET /api/production/group-totals?levels=year,month,week,day&<filters>
```

`levels` defaults to all four. A flat list: coarsest level first, newest first within a level.

```json
{
  "groups": [
    { "level": "year",  "key": "2026",       "label": "2026", "count": 300,
      "income": "...", "expenses": "...", "net": "...", "unpaid": "...", "credit": "..." },
    { "level": "month", "key": "2026-11",    "parent": "2026",     "label": "November", "...": "..." },
    { "level": "week",  "key": "2026-W45",   "parent": "2026-11",  "label": "2 – 8 Nov", "...": "..." },
    { "level": "day",   "key": "2026-11-06", "parent": "2026-W45", "label": "Nov 06, 2026", "...": "..." }
  ]
}
```

- `parent` is the key of the nearest **requested** coarser level, and is absent at the top level.
- Only buckets that have entries are returned.
- A week that spans two months (or two years) is returned **once per parent**, with that parent's share of
  the totals. Look groups up by `(parent, key)`, not by `key` alone.
- Production groups carry `litres`, `entries` and `avg_litres_per_day` instead of the money fields.

## 4) `bucket` on list records

`GET /api/finance/ledger` and `GET /api/production/yield` items now include:

```json
"bucket": { "year": "2026", "month": "2026-11", "week": "2026-W45", "day": "2026-11-06" }
```

It's computed from the entry's farm-local date. Group headers must use the totals from endpoint 3 and never
sum the records that happen to be loaded, so headers stay correct when the list is paginated.

## Errors

Standard envelope `{ "code": "...", "error": "..." }`.

| Status | `code` | When |
|---|---|---|
| 422 | `INVALID_PERIOD` | `period` is not `week`, `month` or `year` |
| 422 | `INVALID_ANCHOR` | `anchor` is not a valid `YYYY-MM-DD` date |
| 422 | `INVALID_LEVELS` | `levels` names anything other than year/month/week/day |
| 400 | `VALIDATION_ERROR` | a list filter is malformed (same messages as the list endpoint) |
| 404 | `NOT_FOUND` | `account_type`/`account_id` names an account outside the tenant |

## Implementation map

| Concern | Module |
|---|---|
| Routes | `app/api/period_totals.py` (production summary dispatched from the existing `/api/production/summary`) |
| Query params | `app/schemas/period_query.py`, `app/schemas/ledger_filters.py`, `app/schemas/production_filters.py` |
| Calendar maths (pure) | `app/services/period_resolver.py` |
| Filter builders (shared with lists) | `app/repositories/ledger_query.py`, `app/repositories/production_query.py` |
| SQL aggregation | `app/repositories/period_totals_repo.py` |
| Services | `app/services/period_totals_service.py` (`LedgerTotalsService`, `ProductionTotalsService`) |
| Formatting | `app/services/period_totals_serializer.py` |
| Income/expense rules | `app/services/ledger_classification.py` |
| Indexes | migration `l4d5e6f7a8b9`: `(tenant_id, farm_id, local_date)` on transactions, `(tenant_id, local_date)` on milk_logs |
