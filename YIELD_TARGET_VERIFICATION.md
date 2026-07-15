# Per-Cow Yield Target Backend Verification & Enhancement

## Current Implementation Status

### What Exists
1. **Per-cow target endpoints** at `/api/v1/animals/{cow_id}/yield-target`
   - POST: Set/update target (in nutrition.py + feed.py)
   - GET: Retrieve target (in nutrition.py + feed.py)
   - Both have v1 aliases

2. **Service layers**
   - `AnimalYieldTargetService` (nutrition.py context)
   - `YieldTargetService` (feed.py context)

3. **Repository layer**
   - `AnimalYieldTargetRepository`

### What Needs Enhancement

## 1. Per-Cow Target Endpoint Response - Missing Fields

### Current Response (GET endpoint)
```json
{
  "target_id": int,
  "cow_id": int,
  "tag_number": str,
  "target_liters": float,
  "times_to_feed_daily": int,
  "base_herd_feed_kg": float,
  "milking_topup_kg": float,
  "status": str
}
```

### Required Enhancement: Add Audit Fields
Frontend expects `updated_at` and `is_active` for sync confidence and freshness:

```json
{
  "target_id": int,
  "cow_id": int,
  "tag_number": str,
  "target_liters": float,
  "times_to_feed_daily": int,
  "base_herd_feed_kg": float,
  "milking_topup_kg": float,
  "status": str,
  "is_active": bool,           // NEW: replaces/clarifies status
  "updated_at": "2026-07-07T14:32:00Z"  // NEW: ISO format
}
```

**Implementation**: Add `updated_at` and `is_active` to AnimalYieldTarget model and return in responses.

---

## 2. Feed Calculation Endpoint - New Parameters Support

### Current Endpoint
`POST /api/v1/feed/calculate-schedule`

Current payload:
```json
{
  "target_liters": number,
  "baseline_herd_meal_kg": number,
  "milking_frequency": int
}
```

### Frontend Now Sends (Additional)
```json
{
  "target_liters": number,
  "baseline_herd_meal_kg": number,
  "milking_frequency": int,
  
  "animal_targets": [            // NEW: per-cow targets
    {
      "cow_id": int,
      "target_liters": number
    }
  ],
  "lactating_cow_ids": [int],    // NEW: which cows are lactating
  "target_mode": str             // NEW: "herd" | "per_cow" | "hybrid"
}
```

### Required Enhancement
Backend should:
1. Accept these new fields without failure
2. Use them if provided (per-cow mode)
3. Fall back to old behavior if not provided (backward compatible)
4. Ignore them if not applicable

**Implementation**: Update `/api/v1/feed/calculate-schedule` to:
- Accept optional `animal_targets`, `lactating_cow_ids`, `target_mode`
- Switch between herd-level and per-cow calculations based on `target_mode`
- Maintain backward compatibility

---

## 3. Target Lifecycle Rules - Validation

### Currently Validated
- target_liters > 0 ✓
- Cow exists ✓
- Belongs to tenant ✓

### Additional Validation Needed
- **Non-LACTATING cows**: Store target but mark as inactive or return clear validation

Current code:
```python
if cow.current_status != CowStatus.LACTATING:
    warnings.append(f'Cow is {cow.current_status}, not LACTATING...')
```

This is good but frontend also needs `is_active=False` in response when cow is not lactating.

---

## 4. Response Format - Key Changes Required

### Changes to AnimalYieldTarget Model
Need to add:
1. `updated_at` timestamp field (auto-update on changes)
2. `is_active` boolean field (derived from cow status or explicit flag)

### Changes to API Responses
All GET/POST endpoints should return:
```json
{
  // ... existing fields ...
  "is_active": bool,           // true if cow is LACTATING and target is active
  "updated_at": "ISO-8601"     // timestamp of last update
}
```

---

## Implementation Tasks

### Task 1: Update AnimalYieldTarget Model
Add fields:
- `updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)`
- `is_active = db.Column(db.Boolean, default=True, nullable=False)`

### Task 2: Update Service Layer Responses
Ensure all endpoint responses include:
- `is_active`: Calculated as `target.is_active and cow.status == LACTATING`
- `updated_at`: ISO format string

### Task 3: Update Feed Calculation Endpoint
Enhance `/api/v1/feed/calculate-schedule` to:
1. Accept new optional fields
2. Check `target_mode` parameter
3. If `target_mode="per_cow"` and `animal_targets` provided:
   - Use provided per-cow targets
   - Filter by `lactating_cow_ids`
4. Otherwise use herd-level calculation (current behavior)
5. Always return same response format

### Task 4: Validation Enhancement
In `AnimalYieldTargetService.set_yield_target()`:
- If cow is not LACTATING: set `is_active=False` in database
- Return warning in response
- Include `is_active: false` in API response

---

## Code Changes Required

### 1. Model Update (`app/models/livestock.py`)
Add to `AnimalYieldTarget` class:
```python
from datetime import datetime

class AnimalYieldTarget(db.Model):
    # ... existing fields ...
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
```

### 2. Service Response Update (`app/services/animal_yield_target_service.py`)
Modify `set_yield_target()` return:
```python
return {
    'target_id': target.id,
    'cow_id': target.animal_id,
    'tag_number': cow.tag_number,
    'target_liters': float(target.target_liters),
    'status': target.status,
    'is_active': target.is_active and cow.current_status == CowStatus.LACTATING,
    'updated_at': target.updated_at.isoformat() if target.updated_at else None,
    'warnings': warnings
}
```

Modify `get_cow_target()` return:
```python
return {
    'target_id': target.id,
    'cow_id': target.animal_id,
    'tag_number': cow.tag_number,
    'target_liters': float(target.target_liters),
    'times_to_feed_daily': target.times_to_feed_daily,
    'base_herd_feed_kg': float(target.base_herd_feed_kg),
    'milking_topup_kg': float(target.milking_topup_kg),
    'status': target.status,
    'is_active': target.is_active and cow.current_status == CowStatus.LACTATING,
    'updated_at': target.updated_at.isoformat() if target.updated_at else None
}
```

### 3. Feed Calculation Endpoint Update (`app/api/feed.py`)
Enhance `/api/v1/feed/calculate-schedule`:
```python
@feed_bp.route('/api/v1/feed/calculate-schedule', methods=['POST'])
def calculate_schedule():
    data = request.get_json() or {}
    
    # Required fields
    target_liters = data.get('target_liters')
    
    # Optional fields (new from frontend)
    baseline_herd_meal_kg = data.get('baseline_herd_meal_kg', 4.0)
    milking_frequency = data.get('milking_frequency')
    animal_targets = data.get('animal_targets')  # NEW
    lactating_cow_ids = data.get('lactating_cow_ids')  # NEW
    target_mode = data.get('target_mode', 'herd')  # NEW: defaults to 'herd' for backward compat
    
    if target_liters is None:
        return jsonify({"error": "target_liters is required"}), 400
    
    try:
        # NEW: Support per-cow calculation mode
        if target_mode == 'per_cow' and animal_targets:
            # Calculate based on per-cow targets
            total_liters = sum(t.get('target_liters', 0) for t in animal_targets)
            schedule = FeedFrequencyHelper.calculate_milking_schedule(
                target_liters=total_liters,
                baseline_herd_meal_kg=baseline_herd_meal_kg,
                milking_frequency=milking_frequency,
            )
        else:
            # OLD: Herd-level calculation (backward compatible)
            schedule = FeedFrequencyHelper.calculate_milking_schedule(
                target_liters=target_liters,
                baseline_herd_meal_kg=baseline_herd_meal_kg,
                milking_frequency=milking_frequency,
            )
        
        return jsonify(schedule), 200
        
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"error": "Failed to calculate schedule", "details": str(exc)}), 500
```

---

## Backward Compatibility

All changes maintain backward compatibility:
1. GET endpoint returns new fields but old code ignores them
2. POST endpoint accepts new fields but old code doesn't send them
3. Feed calculation accepts new fields but treats as optional
4. Existing herd-level mode still works as before

---

## Frontend Sync Indicators

With these changes, frontend can now:
1. Show `updated_at` to user ("Last updated: 5 minutes ago")
2. Show `is_active` status (gray out inactive targets)
3. Check `is_active: false` before using target in calculations
4. Provide more granular control with per-cow mode

---

## Testing

Verify:
1. GET /api/v1/animals/1/yield-target returns `is_active` and `updated_at`
2. POST /api/v1/animals/1/yield-target for non-LACTATING cow sets `is_active: false`
3. POST /api/v1/feed/calculate-schedule with old payload works (backward compat)
4. POST /api/v1/feed/calculate-schedule with new payload works (per-cow mode)
5. Mixed mode (herd targets + new fields) safely ignores new fields

---

## Migration Notes

If AnimalYieldTarget table already exists:
```sql
ALTER TABLE animal_yield_targets 
ADD COLUMN updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
ADD COLUMN is_active BOOLEAN DEFAULT TRUE;
```

If using Flask-Migrate/Alembic:
```bash
flask db migrate -m "Add updated_at and is_active to animal_yield_targets"
flask db upgrade
```
