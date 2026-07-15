# Per-Cow Milk Production Tracking - Backend Implementation

## Architecture Overview

This implementation follows **SOLID principles** and **Single Responsibility Principle (SRP)** with clear separation of concerns:

### Layer Structure

```
API Layer (HTTP contracts, auth, error handling)
    ↓
Service Layer (business logic, validation, orchestration)
    ↓
Repository Layer (data access, persistence)
    ↓
Database (PostgreSQL)
```

## Components

### 1. Repository Layer: `app/repositories/yield_target_repo.py`

**Single Responsibility:** Database access and persistence for yield targets.

**Key Methods:**
- `create()` - Insert new yield target (validates cow exists, enforces constraints)
- `get_by_animal_id()` - Fetch target for specific cow
- `get_by_id()` - Fetch by target ID
- `get_all_active()` - List active targets for tenant
- `get_all_for_lactating_cows()` - List targets for LACTATING cows only
- `update()` - Modify allowed fields
- `deactivate()` - Mark as inactive (soft delete)
- `delete()` - Hard delete

**Principles Applied:**
- **SRP:** Only handles data access; no business logic
- **DRY:** `_resolve_tenant_id()` helper for tenant context extraction
- **Dependency Inversion:** Depends on models, not services
- **Error Handling:** Raises ValueError for business errors, Exception for system errors

---

### 2. Service Layer: `app/services/yield_target_service.py`

**Single Responsibility:** Business logic for yield target management.

**Key Methods:**
- `set_yield_target()` - Create or update target with validation
- `validate_cow_for_target()` - Check cow status eligibility (LACTATING/DRY only)
- `get_yield_target()` - Retrieve with formatted response
- `get_all_yield_targets()` - List all with cow details
- `deactivate_yield_target()` - Deactivate target

**Validation Rules:**
- Target liters > 0
- Base feed kg ≥ 0
- Times to feed ∈ {2, 3, 4}
- Cow status ∈ {LACTATING, DRY}
- Cow must be active
- Only one target per cow

**Principles Applied:**
- **SRP:** Orchestrates business logic; delegates data access to repository
- **Open/Closed:** Can extend with new validation rules without modifying existing code
- **Dependency Inversion:** Depends on repository interface, not implementation details

---

### 3. Service Layer: `app/services/herd_feeding_plan_service.py`

**Single Responsibility:** Calculate herd feeding plans from individual cow targets.

**Key Methods:**
- `calculate_from_cow_targets()` - Aggregate saved targets for LACTATING cows → herd plan
- `calculate_from_manual_targets()` - Calculate from ad-hoc cow targets

**Plan Output Structure:**
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
      "cow_id": 1,
      "cow_tag": "C-001",
      "cow_name": "Bessie",
      "target_liters": 2.5,
      "feed_allocation_kg": 0.48,
      "topup_per_session_kg": 0.12
    }
  ],
  "active_lactating_count": 3,
  "dry_or_inactive_count": 1,
  "total_herd_count": 4
}
```

**Principles Applied:**
- **SRP:** Only calculates plans; doesn't manage targets
- **Single Responsibility Split:** Separate methods for saved vs. manual targets
- **Composition:** Uses `FeedFrequencyHelper` for calculation logic

---

### 4. API Layer: `app/api/feed.py` (Extended)

**Single Responsibility:** HTTP request handling, authentication, response serialization.

#### Endpoints

##### Yield Target Management

**POST `/api/v1/animals/<cow_id>/yield-target`**
- Create/update yield target
- Auth: JWT required
- Body: `{ target_liters, base_herd_feed_kg?, times_to_feed_daily? }`
- Response: 201 (created) or 200 (updated)

**GET `/api/v1/animals/<cow_id>/yield-target`**
- Retrieve specific cow target
- Auth: JWT required
- Response: 200 + target object, or 404

**GET `/api/v1/herd/yield-targets`**
- List all active targets
- Auth: JWT required
- Response: 200 + { count, targets[] }

**PATCH `/api/v1/animals/<cow_id>/yield-target`**
- Update specific target fields
- Auth: JWT required
- Body: Partial update fields
- Response: 200 + updated target

**DELETE `/api/v1/animals/<cow_id>/yield-target`**
- Deactivate target (soft delete)
- Auth: JWT required
- Response: 200 + { status: "Inactive" }

##### Herd Feeding Plan Calculation

**GET `/api/v1/herd/feeding-plan/from-targets?milking_frequency=2`**
- Calculate plan from saved yield targets (LACTATING cows only)
- Auth: JWT required
- Query Params: `milking_frequency` (optional override)
- Response: 200 + herd plan object

**POST `/api/v1/herd/feeding-plan/custom`**
- Calculate plan from ad-hoc cow targets
- Auth: JWT required
- Body: `{ cow_targets: [...], baseline_herd_meal_kg?, milking_frequency? }`
- Response: 200 + herd plan object

---

## Data Flow Examples

### Scenario 1: Setting Individual Cow Targets

```
Frontend: POST /api/v1/animals/5/yield-target
          { target_liters: 2.5 }
          ↓
API Layer: Extract tenant from JWT → validate request
          ↓
YieldTargetService.set_yield_target()
  1. validate_cow_for_target(cow_id=5) → checks status LACTATING/DRY
  2. YieldTargetRepository.get_by_animal_id() → check if exists
  3. YieldTargetRepository.create() or update()
  ↓
Database: INSERT or UPDATE animal_yield_targets
          ↓
Response: { id, cow_id, cow_tag, target_liters, status, action }
```

### Scenario 2: Calculating Herd Feeding Plan

```
Frontend: GET /api/v1/herd/feeding-plan/from-targets
          ↓
API Layer: Extract tenant from JWT
          ↓
HerdFeedingPlanService.calculate_from_cow_targets(tenant_id)
  1. YieldTargetRepository.get_all_for_lactating_cows()
     → SQL JOIN Cow table, filter LACTATING + Active targets
  2. Aggregate total herd target: SUM(target_liters)
  3. FeedFrequencyHelper.calculate_milking_schedule()
     → Calculate meal needs using existing formula
  4. Build per-cow breakdown:
     - proportion = cow.target_liters / total_target
     - allocation = proportion × total_meal_kg
  ↓
Database: Query animal_yield_targets + cows (read-only)
          ↓
Response: {
  herd_total_target_liters,
  total_meal_needed_kg,
  suggested_yard_feedings,
  cow_breakdown: [ { cow_id, target_liters, feed_allocation_kg } ]
}
```

---

## Tenant Isolation

All queries enforce tenant isolation:

```python
# Repository level
query = AnimalYieldTarget.query.filter_by(id=target_id)
if resolved_tenant_id:
    query = query.filter_by(tenant_id=resolved_tenant_id)

# Data retrieval
JoinedQuery: animal_yield_targets
  ↓ JOIN cows ON animal_yield_targets.animal_id = cows.id
  ↓ WHERE animal_yield_targets.tenant_id = ? AND cows.is_active = TRUE
```

**Tenant Resolution Path:**
1. JWT claims → extract `tenant_id`
2. Parse public ID → internal integer
3. Pass to repository methods
4. Enforce at database query level

---

## Error Handling Strategy

### API Layer (HTTP Response)
```python
try:
    result = service.method()
    return jsonify(result), 200
except ValueError:  # Business logic violation
    return jsonify({"error": str(exc)}), 400
except Exception:   # System error
    return jsonify({"error": "...", "details": str(exc)}), 500
```

### Service Layer
```python
# Validation errors
if target_liters <= 0:
    raise ValueError("target_liters must be > 0")  # → 400

# Business rules
if not cow.is_active:
    raise ValueError("Cow not active")  # → 400
```

### Repository Layer
```python
# Constraint violations
if existing_target:
    raise ValueError("Target already exists")  # → 400

# System errors
except SQLAlchemyError as e:
    db.session.rollback()
    raise Exception("Database error")  # → 500
```

---

## Testing Strategy

### Repository Tests (`test_yield_target_repo.py`)
- CRUD operations
- Constraint enforcement
- Tenant isolation
- Query filtering

### Service Tests (`test_yield_target_service.py`)
- Business logic validation
- Cow status eligibility
- Numeric constraints
- Tenant isolation

### Plan Service Tests (`test_herd_feeding_plan.py`)
- Manual target aggregation
- Proportional allocation
- Frequency recommendations
- Herd composition reporting

### API Tests (`test_feed_api.py`)
- HTTP contracts
- Authentication
- Request validation
- Error responses

---

## Extension Points (Open/Closed Principle)

### Adding New Validation Rules
```python
# In YieldTargetService.validate_cow_for_target()
# Just add new conditions without modifying existing logic
```

### Custom Plan Calculations
```python
# Create new service method without touching existing code:
HerdFeedingPlanService.calculate_from_genetic_profile()
```

### New Endpoints
```python
# Add to feed_bp blueprint without modifying existing routes
@feed_bp.route('/api/v1/herd/feeding-plan/ml-optimized', methods=['POST'])
def calculate_optimized_plan():
    # New logic here
```

---

## Database Constraints

```sql
-- animal_yield_targets schema
CREATE TABLE animal_yield_targets (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER NOT NULL,
    animal_id INTEGER NOT NULL,
    target_liters NUMERIC(5, 2) NOT NULL,
    times_to_feed_daily INTEGER DEFAULT 2,
    base_herd_feed_kg NUMERIC(5, 2) DEFAULT 0,
    milking_topup_kg NUMERIC(5, 2) DEFAULT 0,
    status VARCHAR(20) DEFAULT 'Active',
    
    UNIQUE (tenant_id, animal_id),
    CHECK (times_to_feed_daily IN (2, 3, 4)),
    FOREIGN KEY (tenant_id) REFERENCES tenants(id),
    FOREIGN KEY (animal_id) REFERENCES cows(id)
);
```

---

## Migration Path

This implementation is **backward compatible**:

1. Existing `POST /api/v1/feed/calculate-schedule` still works (herd-level input)
2. New endpoints are additions, not replacements
3. Frontend can migrate gradually:
   - Phase 1: Use herd-level calculation (existing)
   - Phase 2: Set per-cow targets (new)
   - Phase 3: Use per-cow plan (new)

---

## Performance Considerations

### Query Optimization
```python
# get_all_for_lactating_cows() uses efficient JOIN
db.session.query(AnimalYieldTarget).join(Cow, ...).filter(...)
# Avoids N+1 query problem

# Index on (tenant_id, status) for list queries
# Index on (tenant_id, animal_id) for lookups
```

### Caching Opportunities
- Herd plans change infrequently (when targets updated)
- Cache plan results keyed by: `(tenant_id, milking_frequency_override)`
- Invalidate on yield target changes

---

## SOLID Principles Checklist

✅ **Single Responsibility:** Each class has one reason to change
  - Repository: Data access
  - Service: Business logic
  - API: HTTP handling

✅ **Open/Closed:** Open for extension, closed for modification
  - New validation rules don't break existing code
  - New endpoints don't modify old endpoints

✅ **Liskov Substitution:** Services can be substituted
  - HerdFeedingPlanService methods have consistent contracts
  - Both `calculate_*` methods return same structure

✅ **Interface Segregation:** Specific, focused contracts
  - YieldTargetService for targets
  - HerdFeedingPlanService for plans
  - Separate concerns

✅ **Dependency Inversion:** Depend on abstractions
  - Services depend on repositories (abstraction)
  - API depends on services (abstraction)
  - Not on concrete implementations
