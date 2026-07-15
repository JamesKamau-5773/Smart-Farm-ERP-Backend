# Animal Yield Target (Per-Cow Milk Production) Backend Implementation

## Overview

This implementation enables the Milk Lab feature to calculate feeding plans based on **individual cow milk production targets** rather than a single herd-level target. It follows SOLID principles and the Single Responsibility Principle (SRP).

## Architecture

### Three-Layer Design

```
┌─────────────────────────────────────────┐
│         API Layer (Flask routes)        │  HTTP interfaces, request validation
├─────────────────────────────────────────┤
│      Service Layer (Business Logic)     │  Orchestration, validation, calculations
├─────────────────────────────────────────┤
│    Repository Layer (Data Access)       │  Database queries, persistence
├─────────────────────────────────────────┤
│           Database (PostgreSQL)         │  Storage
└─────────────────────────────────────────┘
```

### Design Principles

1. **Single Responsibility Principle**
   - Repository: Only handles database queries
   - Service: Only handles business logic and orchestration
   - API: Only handles HTTP requests/responses

2. **Dependency Inversion**
   - Services depend on repositories, not the other way around
   - Repositories are stateless helpers

3. **Tenant Isolation**
   - Every query enforces tenant context
   - Multi-tenant safety at the repository level

4. **Error Handling**
   - Clear error messages for validation failures
   - Proper HTTP status codes (400, 404, 500)

---

## API Endpoints

All endpoints require JWT authentication. Tenant context is extracted from JWT claims.

### 1. Set Yield Target for a Cow

```http
POST /api/v1/animals/{cow_id}/yield-target
Content-Type: application/json
Authorization: Bearer <token>

{
  "target_liters": 2.5
}
```

**Response (201 Created):**
```json
{
  "target_id": 42,
  "cow_id": 1,
  "tag_number": "C-001",
  "target_liters": 2.5,
  "status": "Active",
  "warnings": []
}
```

**Errors:**
- `400` - Missing/invalid target_liters or cow not found
- `401` - No valid JWT token

---

### 2. Get Yield Target for a Cow

```http
GET /api/v1/animals/{cow_id}/yield-target
Authorization: Bearer <token>
```

**Response (200 OK):**
```json
{
  "target_id": 42,
  "cow_id": 1,
  "tag_number": "C-001",
  "target_liters": 2.5,
  "times_to_feed_daily": 2,
  "base_herd_feed_kg": 0.0,
  "milking_topup_kg": 0.0,
  "status": "Active"
}
```

**Errors:**
- `404` - No target set for this cow

---

### 3. List All Herd Targets

```http
GET /api/v1/herd/yield-targets
Authorization: Bearer <token>
```

**Response (200 OK):**
```json
{
  "total_cows": 3,
  "targets": [
    {
      "target_id": 42,
      "cow_id": 1,
      "tag_number": "C-001",
      "cow_name": "Daisy",
      "target_liters": 2.5,
      "times_to_feed_daily": 2,
      "status": "Active"
    },
    {
      "target_id": 43,
      "cow_id": 2,
      "tag_number": "C-002",
      "cow_name": "Bessie",
      "target_liters": 1.8,
      "times_to_feed_daily": 2,
      "status": "Active"
    }
  ]
}
```

---

### 4. Calculate Herd Feeding Plan

Calculates meal requirements based on all active per-cow targets.

```http
GET /api/v1/herd/feeding-plan?baseline_herd_meal_kg=4.0&milking_frequency=2
Authorization: Bearer <token>
```

**Query Parameters:**
- `baseline_herd_meal_kg` (optional, default 4.0): Base daily meal for entire herd
- `milking_frequency` (optional, 2-4): Override automatic frequency detection

**Response (200 OK):**
```json
{
  "total_herd_target_liters": 4.3,
  "total_meal_needed_kg": 3.73,
  "base_herd_mix_kg": 4.0,
  "extra_milking_topup_total_kg": 0.73,
  "per_milking_session_kg": 0.37,
  "suggested_yard_feedings": 2,
  "used_milking_frequency": 2,
  "farmer_reasoning": "Standard layout. 2 daily feedings.",
  "number_of_cows": 2,
  "per_cow_breakdown": [
    {
      "cow_id": 1,
      "tag": "C-001",
      "target_liters": 2.5,
      "feed_allocation_kg": 2.17,
      "topup_kg": 0.43
    },
    {
      "cow_id": 2,
      "tag": "C-002",
      "target_liters": 1.8,
      "feed_allocation_kg": 1.56,
      "topup_kg": 0.30
    }
  ]
}
```

**Errors:**
- `400` - No active targets found for lactating cows

**How it works:**
1. Fetches all targets for LACTATING cows with `is_active=True`
2. Calculates herd total milk target (sum of individual targets)
3. Uses `FeedFrequencyHelper` to calculate total meal needed
4. **Allocates feed proportionally**: Cow targeting 2.5L out of 4.3L total gets 58% of feed
5. Returns per-cow breakdown with individual feed allocation

---

### 5. Delete Yield Target

```http
DELETE /api/v1/animals/{cow_id}/yield-target
Content-Type: application/json
Authorization: Bearer <token>

{
  "target_id": 42
}
```

**Response (200 OK):**
```json
{
  "message": "Yield target deleted successfully."
}
```

---

## Code Structure

### Repository Layer

**File:** `app/repositories/animal_yield_target_repo.py`

Handles all database operations. Methods:

```python
class AnimalYieldTargetRepository:
    # Get target by ID
    get_by_id(target_id, tenant_id) -> AnimalYieldTarget | None
    
    # Get target for specific cow
    get_by_cow_id(cow_id, tenant_id) -> AnimalYieldTarget | None
    
    # Get all active targets (LACTATING cows only)
    get_active_targets_for_herd(tenant_id) -> list[AnimalYieldTarget]
    
    # Get all targets (active and inactive)
    get_all_targets_for_herd(tenant_id) -> list[AnimalYieldTarget]
    
    # Create or update target
    create_or_update(tenant_id, cow_id, target_liters, ...) -> AnimalYieldTarget
    
    # Mark as inactive (don't delete, preserve history)
    deactivate(target_id, tenant_id) -> bool
    
    # Permanently delete
    delete(target_id, tenant_id) -> bool
```

**Key Properties:**
- All methods enforce tenant isolation
- Returns domain objects (AnimalYieldTarget model instances)
- No business logic - pure data access
- Raises specific exceptions for errors

---

### Service Layer

**File:** `app/services/animal_yield_target_service.py`

Handles business logic. Methods:

```python
class AnimalYieldTargetService:
    # Set/update yield target with validation
    set_yield_target(tenant_id, cow_id, target_liters, validate_status=True) -> dict
    
    # Get target for cow
    get_cow_target(tenant_id, cow_id) -> dict | None
    
    # List all targets in herd
    list_herd_targets(tenant_id) -> list[dict]
    
    # Calculate aggregated feeding plan
    calculate_herd_feeding_plan(
        tenant_id, 
        baseline_herd_meal_kg=4.0,
        milking_frequency=None,
        use_saved_targets=True
    ) -> dict
    
    # Deactivate target
    deactivate_target(tenant_id, target_id) -> dict
    
    # Delete target
    delete_target(tenant_id, target_id) -> dict
    
    # Respond to cow status changes
    handle_cow_status_change(cow_id, new_status, tenant_id) -> None
```

**Key Properties:**
- Validates all inputs
- Catches and transforms errors into meaningful messages
- Returns DTOs (dictionaries) - safe for serialization
- Orchestrates between repositories
- Integrates with FeedFrequencyHelper

---

### API Layer

**File:** `app/api/nutrition.py` (updated)

Flask Blueprint routes:

```python
# Set target
POST /api/v1/animals/<cow_id>/yield-target
@jwt_required()
@role_required(Role.FARMER, Role.FARM_HAND)

# Get target
GET /api/v1/animals/<cow_id>/yield-target
@jwt_required()
@role_required(Role.FARMER, Role.FARM_HAND, Role.VET)

# List herd targets
GET /api/v1/herd/yield-targets
@jwt_required()
@role_required(Role.FARMER, Role.FARM_HAND, Role.VET)

# Calculate plan
GET /api/v1/herd/feeding-plan
@jwt_required()
@role_required(Role.FARMER, Role.FARM_HAND, Role.VET)

# Delete target
DELETE /api/v1/animals/<cow_id>/yield-target
@jwt_required()
@role_required(Role.FARMER)
```

**Key Properties:**
- Extracts tenant from JWT claims
- Parses and validates request data
- Calls service layer
- Returns proper HTTP responses with status codes
- Includes both `/api/v1/` and alias routes

---

## Data Model Integration

### AnimalYieldTarget Table

```python
class AnimalYieldTarget(db.Model):
    id: int (PK)
    tenant_id: int (FK → Tenant, indexed)
    animal_id: int (FK → Cow)
    target_liters: Decimal(5, 2)
    times_to_feed_daily: int (2, 3, or 4)
    base_herd_feed_kg: Decimal(5, 2)
    milking_topup_kg: Decimal(5, 2)
    status: str ('Active' or 'Inactive')
```

### Relationships

- Cows with status `LACTATING` and `is_active=True` are included in feeding plans
- Cows with status `DRY`, `HEIFER`, or `CALF` are excluded
- When a cow changes status to `DRY`, its target is auto-deactivated
- Targets for inactive cows are never included

---

## Feeding Plan Calculation Example

**Scenario:**
- Cow 1: 15L target (60%)
- Cow 2: 10L target (40%)
- Baseline herd meal: 4.0 kg

**Calculation:**
1. Total herd target = 15 + 10 = 25L
2. Total meal needed = max(0, (25 - 10) / 1.5) = 10 kg
3. Milking topup = 10 - 4 = 6 kg
4. Per-session topup = 6 / 2 = 3 kg

**Per-Cow Allocation:**
- Cow 1: 6 kg × 0.6 = 3.6 kg meal, 3 kg × 0.6 = 1.8 kg topup
- Cow 2: 6 kg × 0.4 = 2.4 kg meal, 3 kg × 0.4 = 1.2 kg topup

---

## Testing

### Test Files

1. **`tests/test_animal_yield_target_repository.py`** (Unit tests)
   - Tests repository methods in isolation
   - Verifies tenant isolation
   - Tests error handling

2. **`tests/test_animal_yield_target_service.py`** (Unit tests)
   - Tests service business logic
   - Verifies validation
   - Tests feeding plan calculations
   - Tests proportional allocation

3. **`tests/test_animal_yield_target_api.py`** (Integration tests)
   - Tests API endpoints end-to-end
   - Verifies HTTP status codes
   - Tests request/response serialization

### Running Tests

```bash
# Run all tests for this feature
python -m pytest tests/test_animal_yield_target_*.py -v

# Run specific test class
python -m pytest tests/test_animal_yield_target_service.py::TestAnimalYieldTargetService -v

# Run with coverage
python -m pytest tests/test_animal_yield_target_*.py --cov=app/services/animal_yield_target_service --cov=app/repositories/animal_yield_target_repo
```

---

## Usage Workflow

### Frontend Integration

1. **Set targets for each lactating cow:**
   ```javascript
   POST /api/v1/animals/1/yield-target
   { "target_liters": 2.5 }
   ```

2. **Display herd targets:**
   ```javascript
   GET /api/v1/herd/yield-targets
   ```

3. **Calculate and display feeding plan:**
   ```javascript
   GET /api/v1/herd/feeding-plan
   ```

4. **Handle cow status changes:**
   - When cow changes to DRY, target auto-deactivates
   - When cow returns to LACTATING, can set new target

---

## Error Handling

### Common Errors

| Scenario | Status | Response |
|----------|--------|----------|
| Missing target_liters | 400 | `{"error": "target_liters is required."}` |
| Negative liters | 400 | `{"error": "target_liters must be greater than 0."}` |
| Cow not found | 400 | `{"error": "Cow {id} not found for this tenant."}` |
| No active targets | 400 | `{"error": "No active yield targets found..."}` |
| Target not found | 404 | `{"error": "Yield target not found..."}` |
| Invalid frequency | 400 | `{"error": "milking_frequency must be 2, 3, or 4."}` |
| No auth token | 401 | JWT error |
| Wrong tenant | 403 | Tenant isolation enforced |

---

## Future Enhancements

1. **Per-cow feeding adjustments**
   - Allow different meal types per cow
   - Support individual supplement additions

2. **Historical tracking**
   - Archive target changes
   - Track plan effectiveness

3. **ML-based recommendations**
   - Suggest targets based on past production
   - Predict optimal feed combinations

4. **Batch operations**
   - Set targets for multiple cows at once
   - Import from CSV

---

## Developer Notes

### Adding a New Endpoint

1. **Service method** in `AnimalYieldTargetService`
   - Add business logic
   - Return dict for JSON serialization
   - Raise ValueError for user errors, Exception for system errors

2. **Repository method** in `AnimalYieldTargetRepository`
   - Add database query
   - Enforce tenant isolation
   - Return domain objects

3. **API route** in `app/api/nutrition.py`
   - Add Flask route
   - Use `@jwt_required()` and `@role_required()`
   - Call service method
   - Return JSON with appropriate status code

### Testing a New Endpoint

1. Add unit test to `test_animal_yield_target_service.py`
2. Add integration test to `test_animal_yield_target_api.py`
3. Run tests with `pytest -v`

---

## Conclusion

This implementation provides a production-ready, maintainable system for per-cow yield targets with:

- ✅ SOLID design principles
- ✅ Complete separation of concerns
- ✅ Full test coverage
- ✅ Tenant isolation
- ✅ Clear error handling
- ✅ Proportional feed allocation
- ✅ Auto-deactivation on status changes

The frontend can now display accurate, per-cow feeding recommendations based on individual milk production targets.
