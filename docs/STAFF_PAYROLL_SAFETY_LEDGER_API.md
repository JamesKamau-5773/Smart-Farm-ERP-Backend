# Staff, Payroll, Milk Safety & Ledger: API Changes

**Status:** Implemented on branch `development`. Migration `k3c4d5e6f7a8`.
**Last updated:** 2026-11-03

Changes are additive unless they're marked ⚠️.

**Errors:** every error from `/api/hr/*`, `/api/finance/*`, `/api/safety/*`, `/api/clinical/*` and `/api/veterinary/*` now has this shape:

```json
{ "code": "MACHINE_READABLE_CODE", "error": "Message to show", "...": "extra fields where listed" }
```

Branch on `code`. If an endpoint doesn't set a specific code, one comes from the HTTP status: `400 VALIDATION_ERROR`, `401 UNAUTHENTICATED`, `403 FORBIDDEN`, `404 NOT_FOUND`, `409 CONFLICT`, `422 UNPROCESSABLE`.

---

## 1. Staff

### `POST /api/hr/staff/{id}/offboard` (new, owner)
```json
{ "end_date": "2026-06-10", "offboarding_reason": "RESIGNED", "offboarding_note": "Moved to Nakuru" }
```

**Request**
- `offboarding_reason` is one of `RESIGNED`, `CONTRACT_ENDED`, `DISMISSED`, `REDUNDANCY`, `RETIRED`, `DECEASED` or `OTHER`. A note is required for `OTHER`.
- `end_date` is the last working day. It defaults to today. It can't be in the future or before the hire date.

**What happens on success**
- The employee's status becomes `INACTIVE`.
- Their login is disabled, **every session they have is signed out**, and any pending invite is cancelled.
- The response is `200` with the staff record. These new fields are filled in:
  - `end_date`
  - `offboarding_reason`
  - `offboarding_note`
  - `offboarded_at`
  - `is_offboarded: true`
- Payroll pays the month they leave pro rata (see `days_paid`) and leaves them out of every later month.

**Errors**

| HTTP | `code` | Meaning |
|---|---|---|
| `409` | `LOAN_OUTSTANDING` | An advance is still owed. The response includes `loan_balance`. Record a repayment, or recover the balance through a final payroll run, first. |
| `409` | `ALREADY_OFFBOARDED` | The employee has already been offboarded. |
| `400` | `VALIDATION_ERROR` | A field is invalid. |

### `DELETE /api/hr/staff/{id}` (new, owner)
- Only for records created by mistake. On success: `200 { "deleted": true, "id": 7 }`.
- `409 HAS_HISTORY` means the employee has payroll, advances or ledger entries on record. The response includes:
  - `history`, for example `["payroll", "advances"]`
  - `can_offboard`

  Offer **Offboard** instead.

### Staff record: new field
- `statutory_deductions_enabled` (default `true`) can be set on create or `PATCH`.
- Turn it off only for staff whose PAYE, NSSF, SHIF and Housing Levy are handled outside this payroll.

---

## 2. Advances

### `POST /api/hr/staff/{id}/advances` (new, owner)
```json
{ "amount": 1500, "date": "2026-06-04", "note": "School fees", "record_expense": true }
```
- The server adds the amount to the balance. Two advances issued at the same moment both count.
- `201` returns `{ "movement": {...}, "loan_balance": 3500 }`.
- `record_expense` defaults to `true`. It posts the cash paid out to the ledger as **Labor / Wages: Salary advance**. Send `false` only if the farmer already recorded it by hand.
- `409 EMPLOYEE_OFFBOARDED` is returned for an employee who has left.

### `POST /api/hr/staff/{id}/advance-repayments` (new, owner)
- Body: `{ "amount", "date"?, "note"? }`.
- Records cash the employee paid back outside payroll.
- A repayment can't be more than the balance (`400 VALIDATION_ERROR`).

### `GET /api/hr/staff/{id}/advances` (new)
```json
{ "loan_balance": 3500, "monthly_deduction": 1000,
  "movements": [{ "id": 3, "kind": "ADVANCE", "amount": 1500, "balance_after": 3500, "date": "2026-06-04",
                  "note": "School fees", "payroll_run_id": null, "ledger_transaction_id": 88 }] }
```
- `kind` is one of:
  - `ADVANCE`
  - `REPAYMENT`
  - `PAYROLL_DEDUCTION`, which is recorded when a payroll run is paid. `payroll_run_id` is set on these.
- Newest first.

⚠️ **`PATCH /api/hr/staff/{id}` can no longer change `loan_balance`.**
- A different value returns `400 BALANCE_CHANGE_REQUIRES_ADVANCE`.
- Sending the unchanged value is fine.
- `monthly_deduction` can still be edited.

---

## 3. Payroll

### ⚠️ Statutory deductions
Each line now deducts PAYE, NSSF, SHIF and the Housing Levy. **Net pay is lower than before for every employee with statutory deductions on.**

Order of calculation:
1. Pay for the days employed.
2. Less unpaid leave and absence.
3. Statutory deductions on what was earned.
4. Advance recovery from what is left.

Advance recovery never cuts into statutory amounts, and net pay never goes below 0.

The run's month picks the rate schedule:

| Schedule | From | NSSF (employee and employer) | SHIF (employee only) | Housing Levy | PAYE |
|---|---|---|---|---|---|
| `KE-2025-02` | Feb 2025 | 6% of pay up to 72,000 | 2.75%, min 300 | 1.5% employee + 1.5% employer | 10 / 25 / 30 / 32.5 / 35%, relief 2,400 |
| `KE-2026-02` | Feb 2026 | 6% of pay up to 108,000 | 2.75%, min 300 | 1.5% employee + 1.5% employer | same |

NSSF, SHIF and the Housing Levy are deducted before PAYE is worked out.

**Example: KES 30,000 a month in 2026**

| Item | KES |
|---|---|
| NSSF | 1,800 |
| SHIF | 825 |
| Housing Levy | 450 |
| PAYE | 731.25 |
| **Net pay** (no advance) | **26,193.75** |
| Employer also pays: NSSF + Housing Levy | 2,250 |

**New fields on each line.** Like the other HR fields, each comes in camelCase and snake_case:
- `days_paid`, which is `null` for a full month
- `taxable_pay`, `paye`
- `nssf_employee`, `nssf_employer`
- `shif`
- `housing_levy_employee`, `housing_levy_employer`
- `total_statutory_deductions`
- `statutory_rates_version`

**New totals on the run**
- `total_paye`
- `total_nssf_employee`, `total_nssf_employer`
- `total_shif`
- `total_housing_levy_employee`, `total_housing_levy_employer`
- `total_employer_contributions`

`totalDeductions` now includes the statutory deductions.

**Ledger.** Finalizing a run posts two entries:
- `PAYROLL-YYYY-MM`: net wages.
- `PAYROLL-YYYY-MM-STATUTORY`: the employee deductions plus the employer's NSSF and Housing Levy, owed to KRA, NSSF and SHA.

### `GET /api/hr/payroll/runs/summary?limit=24` (new)
```json
{ "next_period": { "id": "2026-07", "payroll_year": 2026, "payroll_month": 7, "existing_status": null },
  "runs": [{ "id": "2026-06", "payroll_year": 2026, "payroll_month": 6, "status": "Paid", "staff_count": 4,
             "total_gross_pay": 120000, "total_deductions": 21000, "total_net_pay": 99000,
             "generated_at": "…", "finalized_at": "…", "paid_at": "…" }] }
```
- One request for the run history screen. **Stop fetching every run's details.**
- `next_period` is:
  - the open draft's month, if there is one;
  - otherwise the month after the latest run;
  - otherwise this month, when there are no runs yet.
- `limit` is 1–120 and defaults to 24.

### `GET /api/hr/payroll/runs/{YYYY-MM}/payslips/{staff_id}.pdf` (new, owner)
- Returns an A5 PDF built from the stored line. It shows earnings, deductions, net pay, employer contributions and the advance balance after this payroll.
- `409 PAYROLL_NOT_FINALIZED` while the run is still a draft.
- `404 NOT_FOUND` if the employee isn't on that run.

---

## 4. Milk safety

### `GET /api/safety/dashboard` (also `/api/veterinary/hardlocks/active`): changed

⚠️ **Fix:** the withdrawal end now comes from the treatment whose withdrawal ends **last**. Before, it came from the latest treatment, which could hide a withdrawal that was still running.

The severity filter is now applied before paging, so the counts are right.

**New fields on each item**

| Field | Meaning |
|---|---|
| `withdrawal_ends_at` | Exact ISO date-time the treatment withdrawal ends. |
| `hold_until` | End of a manual hold, if one was set. |
| `lock_expires` | The later of the two. |
| `withdrawal_active` | `true` while the withdrawal is still running. |
| `can_release` | `false` while the withdrawal runs or the latest test failed. |
| `source` | `treatment` or `manual`. |
| `treated_at` | When the treatment was given. |
| `vet_id`, `vet_name` | The vet who gave the treatment. |
| `latest_test` | The most recent milk test, if any. |

⚠️ `updated_by` is now a **name**, not a user id.

### `POST /api/safety/holds` (new; farmer, vet or farm hand)
```json
{ "cow_id": 12, "reason": "Blood in milk", "until": "2026-11-05T06:00:00+03:00", "notes": "Check at morning milking" }
```
- `until` is optional and must be in the future.
- `201` returns the board item.
- Anyone who can see the board can place a hold. Releasing one stays with the farmer.

### `POST /api/safety/milk-tests` (new; farmer, vet or farm hand)
```json
{ "cow_id": 12, "test_type": "Antibiotic residue", "result": "PASS", "tested_at": "2026-11-03T07:30:00+03:00", "notes": "Delvotest" }
```
- A `FAIL` puts the cow's milk on hold automatically.
- A `PASS` doesn't release the milk by itself. The farmer still releases it.
- `201` returns `{ "test", "placed_on_hold", "hold" }`.

### `GET /api/safety/cows/{cow_id}/milk-tests` (new)
- Returns `{ "items": [...] }`, newest first. Each test includes `recorded_by_name`.

### ⚠️ `PUT /api/clinical/cows/{id}/hardlock` with `{ "is_locked": false }`
- Returns `409 WITHDRAWAL_ACTIVE`, with `withdrawal_ends_at`, while a treatment's withdrawal is running.
- To release early, send `override_reason`. The override is written to the audit log.
- Releasing clears any manual hold.

---

## 5. Ledger

### `GET /api/finance/categories` (new)
```json
{ "revenue": [{ "value": "Milk Sale", "label": "Milk Sale" }],
  "expense": [{ "value": "Feed Purchase", "label": "Feed Purchase", "default_cost_class": "COGS" }],
  "cost_classes": [{ "value": "COGS", "label": "Production cost" }] }
```
Use this instead of hard-coded lists. The server validates entries against the same rules.

### `POST /api/finance/transactions/{id}/corrections`: changed
The old path `/void-and-replace` still works.
```json
{ "void_reason": "Typed 1200 instead of 1500", "replacement": { "amount": 1500, "category": "Transport", "cost_class": "OPERATING" } }
```
- `amount` is new. Every `replacement` field is optional and keeps the original value when left out.
- **Income entries can now be corrected.** The original receipt is voided and a new one is issued for the corrected amount. `cost_class` isn't allowed on income.
- These return `422`:
  - Income linked to a customer or buyer account. Correct it through that account.
  - A different amount on an entry posted automatically (stock, payroll, advances) or split across animals. Its category can still be corrected.
- `201` returns `{ "voided_transaction", "replacement_transaction" }`.

### Receipt photos
**Upload:** `POST /api/finance/transactions/{id}/attachments`
- Send multipart form data with the file in the `file` field.
- Accepted: JPEG, PNG, WebP or PDF, up to 4 MB. An entry can have at most 5.
- `201` returns `{ "id", "url", "content_type", "size_bytes", "filename", "uploaded_at" }`.

**Download:** `GET {url}`
- Needs the user's login, and only works for their own farm.
- Fetch it with the API client as a blob, not a plain `<img src>`.

**Elsewhere**
- Ledger rows now include `attachments` and `receipt.status`.
- A correction carries the attachments over to the replacement entry.
