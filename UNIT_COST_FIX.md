# Fix for `/api/finance/unit-cost` 400 Errors

## Problem
The `/api/finance/unit-cost` endpoint was returning `400 Bad Request` with message "Missing or invalid tenant context" repeatedly, causing React Query to retry the request in a loop.

## Root Cause Analysis
The endpoint requires a valid `tenant_id` from either:
1. `g.tenant_id` set by the middleware (`set_tenant_context()`)
2. JWT claims (fallback)

If `_get_tenant_id_from_context()` couldn't extract a valid tenant_id, the endpoint returned 400.

## Solution Applied

### Change 1: Enhanced `_get_tenant_id_from_context()` Function
**File**: `app/api/finance.py` (lines 17-32)

Added fallback logic to check JWT claims if `g.tenant_id` is not set:

```python
def _get_tenant_id_from_context():
    tenant_public_id = getattr(g, 'tenant_id', None)
    
    # Fallback: check JWT claims if g.tenant_id is not set
    if not tenant_public_id:
        try:
            from flask_jwt_extended import get_jwt
            claims = get_jwt() or {}
            tenant_public_id = claims.get('tenant_id')
        except (RuntimeError, Exception):
            pass
    
    if not tenant_public_id:
        return None
    try:
        return parse_public_int_id(tenant_public_id, 'tenant_')
    except (TypeError, ValueError):
        return None
```

**Benefits**:
- More resilient to middleware failures
- Reduces 400 errors from missing tenant context
- Applies to all finance endpoints that use this function

### Change 2: Improved Error Diagnostics
**File**: `app/api/finance.py` (lines 85-106)

Enhanced the `/api/finance/unit-cost` endpoint to provide detailed diagnostic info:

```python
@finance_bp.route('/unit-cost', methods=['GET'])
@jwt_required()
@role_required(Role.FARMER)
def get_unit_cost():
    """Retrieves the real-time cost of production per liter."""
    from flask_jwt_extended import get_jwt
    
    tenant_id = _get_tenant_id_from_context()
    if tenant_id is None:
        # Provide diagnostic information for debugging
        claims = get_jwt() or {}
        raw_tenant_id = getattr(g, 'tenant_id', 'NOT_SET')
        print(f"[unit-cost] DEBUG: g.tenant_id={raw_tenant_id}, JWT tenant_id={claims.get('tenant_id')}, user_id={claims.get('sub')}")
        return jsonify({
            'error': 'Missing or invalid tenant context.',
            'details': {
                'g_tenant_id': raw_tenant_id,
                'jwt_tenant_id': claims.get('tenant_id'),
                'user_id': claims.get('sub'),
            }
        }), 400

    return FinanceService.calculate_daily_unit_cost(tenant_id=tenant_id)
```

**Benefits**:
- If 400 errors still occur, they now include debugging info
- Helps identify whether the issue is with middleware or JWT claims
- Prints debug info to Flask logs for server-side analysis

## Testing

All tests pass:
```bash
python -m pytest tests/test_finance.py -x
# Result: 7 passed in 19.73s
```

Specific unit-cost test:
```bash
python -m pytest tests/test_finance.py::FinanceTestCase::test_get_unit_cost -xvs
# Result: PASSED
```

## How to Test in Production

1. **Restart the backend server** to apply changes
2. **Navigate to the Finance dashboard** (CommandCenter page)
3. **Check for "Profit per Liter" card**:
   - Should show a monetary value (e.g., "KES 42.50")
   - Should NOT show "—" (loading) repeatedly
4. **Check browser console** for any errors
5. **Check Flask logs** for debug output if errors still occur

## If 400 Errors Persist

1. Check Flask logs for the debug output:
   ```
   [unit-cost] DEBUG: g.tenant_id=..., JWT tenant_id=..., user_id=...
   ```
2. Look for patterns in the output:
   - If `g.tenant_id=NOT_SET` and `JWT tenant_id=None`: JWT claims missing tenant_id
   - If `g.tenant_id=NOT_SET` and `JWT tenant_id=tenant_...`: Fallback is working, but other issue present
   - If `user_id=None`: JWT not being sent or is invalid
3. Check if user is properly authenticated (JWT token in sessionStorage)

## Related Issue: `/api/customers` 404

The backend only has routes at `/api/finance/customers`. The frontend correctly calls this endpoint through `financeApi.customers()`. If 404s are still appearing:

1. These are likely stale browser cache entries
2. Clear browser cache and try again
3. Or check the exact path in browser Network tab to verify actual requests

## Files Modified

- `backend/app/api/finance.py`:
  - Updated `_get_tenant_id_from_context()` function (lines 17-32)
  - Enhanced `get_unit_cost()` endpoint (lines 85-106)

## Rollback Instructions

If needed, the original functions can be restored from git:
```bash
git checkout app/api/finance.py
```
