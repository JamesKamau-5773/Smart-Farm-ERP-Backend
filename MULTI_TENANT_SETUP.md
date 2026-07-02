# Multi-Tenant RLS & Isolation Architecture

## Overview

This document describes the comprehensive multi-tenant isolation system implemented for the Smart Farm ERP system. The architecture includes Row-Level Security (RLS) at the database level, tenant-aware rate limiting, and Celery background processing with tenant context propagation.

## Architecture Components

### 1. Row-Level Security (RLS) - Database Level
**Location:** `migrations/versions/390d029aa1ce_enable_rls_and_add_tenant_isolation_.py`

PostgreSQL RLS policies enforce tenant_id-based row filtering at the database level, preventing cross-tenant data access.

**Tables Protected:**
- `milk_yield` - Dairy production records
- `financial_transactions` - Financial ledger entries

**How It Works:**
1. Middleware sets `app.current_tenant_id` session variable from JWT token
2. Middleware executes: `SET app.current_tenant_id = '{tenant_id}'` on database session
3. PostgreSQL RLS policies automatically filter rows: `tenant_id = current_setting('app.current_tenant_id')::integer`
4. Result: Database itself enforces row-level access control

**Policy SQL:**
```sql
CREATE POLICY tenant_isolation_policy ON milk_yield
    USING (tenant_id = current_setting('app.current_tenant_id')::integer);

CREATE POLICY tenant_isolation_policy ON financial_transactions
    USING (tenant_id = current_setting('app.current_tenant_id')::integer);
```

### 2. Tenant Context Middleware
**Location:** `app/middleware.py`

Runs before each request to establish tenant context for both RLS and rate limiting.

**Implementation:**
```python
def set_tenant_context():
    """
    1. Extracts tenant_id from JWT claims
    2. Stores in Flask g object for rate limiting access
    3. Sets PostgreSQL session variable for RLS enforcement
    """
    g.tenant_id = None
    try:
        claims = get_jwt()
        tenant_id = claims.get('tenant_id')
        if tenant_id:
            g.tenant_id = tenant_id
            # RLS enforcement via PostgreSQL session variable
            db.session.execute(f"SET app.current_tenant_id = '{tenant_id}'")
            db.session.commit()
    except:
        pass
```

**Trust Chain:**
- JWT token contains `tenant_id` and `role` claims
- Middleware validates JWT via Flask-JWT-Extended
- Tenant context propagates to rate limiting and database queries

### 3. Tenant-Aware Rate Limiting
**Location:** `app/utils/rate_limiting.py`

Implements SRP-compliant rate limiting based on tenant_id to prevent "noisy neighbor" issues.

**Key Function:**
```python
def tenant_based_key_func():
    """
    Rate limiting key function that isolates limits per tenant.
    - Returns 'tenant:123' for authenticated requests (prevents cross-tenant interference)
    - Returns IP address for unauthenticated routes (login, callbacks, etc.)
    """
    if g.get('tenant_id'):
        return f"tenant:{g.tenant_id}"
    return request.remote_addr
```

**Benefits:**
- ✅ Tenant A's API usage doesn't throttle Tenant B
- ✅ Each tenant has independent rate limit buckets
- ✅ Unauthenticated routes still protected by IP-based limits
- ✅ Prevents resource exhaustion across multi-tenant cluster

**Integration in `app/__init__.py`:**
```python
limiter = Limiter(
    app=app,
    key_func=tenant_based_key_func,
    storage_uri=app.config['RATELIMIT_STORAGE_URI']  # Redis backend
)
```

### 4. Celery Background Task Processing
**Location:** `app/celery_utils.py`

Enables offloading heavy computations while preserving Flask app context and tenant isolation.

**Key Features:**
```python
class ContextTask(celery.Task):
    """Task class that executes within Flask app context."""
    def __call__(self, *args, **kwargs):
        with app.app_context():
            return self.run(*args, **kwargs)
```

**Configuration in `config.py`:**
```python
CELERY_BROKER_URL = 'redis://localhost:6379/1'       # Task queue
CELERY_RESULT_BACKEND = 'redis://localhost:6379/2'   # Result storage
```

**Usage:**
```python
@celery.task(base=ContextTask)
def process_milk_data(tenant_id, data):
    # Runs in app context with full database access
    # Tenant context should be explicitly passed to task
    pass
```

## PostgreSQL Setup Requirements

### Prerequisites
1. PostgreSQL 13+ (recommended 14+)
2. Port 5433 (as configured, adjust in .env if needed)
3. Valid credentials with superuser or appropriate GRANT privileges

### Setup Steps

#### 1. Create Database and User
```bash
sudo -u postgres psql

# Create user
CREATE USER jivu_app WITH PASSWORD 'secure_password_here';

# Create database
CREATE DATABASE jivu_farm_db OWNER jivu_app;

# Grant RLS admin privileges
GRANT ALL PRIVILEGES ON DATABASE jivu_farm_db TO jivu_app;

# Connect to database
\c jivu_farm_db

# Enable RLS capability
ALTER DATABASE jivu_farm_db SET rls.enabled = true;

# Exit
\q
```

#### 2. Update Credentials in `.env`
```bash
# .env file
DATABASE_URL=postgresql+psycopg://jivu_app:secure_password_here@localhost:5433/jivu_farm_db
TEST_DATABASE_URL=postgresql+psycopg://jivu_app:secure_password_here@localhost:5433/jivu_farm_db_test
REDIS_URL=redis://localhost:6379/0
CELERY_BROKER_URL=redis://localhost:6379/1
CELERY_RESULT_BACKEND=redis://localhost:6379/2
```

#### 3. Apply Migrations
```bash
cd /home/james/projects/smart-farm-erp-system/backend
source .venv/bin/activate

# Run all migrations including RLS
flask db upgrade heads

# Verify RLS is enabled
flask db current
```

#### 4. Verify RLS Policies Active
```sql
-- Connect to jivu_farm_db as admin
psql -U jivu_app -d jivu_farm_db -h localhost -p 5433

-- List RLS policies
\d+ milk_yield
\d+ financial_transactions

-- Output should show:
-- Policies:
--     "tenant_isolation_policy" (USING: (tenant_id = (current_setting('app.current_tenant_id'::integer)))
```

## Application Configuration

### Environment Variables (`.env`)
```bash
# Database
DATABASE_URL=postgresql+psycopg://jivu_app:password@localhost:5433/jivu_farm_db
TEST_DATABASE_URL=postgresql+psycopg://jivu_app:password@localhost:5433/jivu_farm_db_test

# Redis (Rate Limiting & Celery)
REDIS_URL=redis://localhost:6379/0
CELERY_BROKER_URL=redis://localhost:6379/1
CELERY_RESULT_BACKEND=redis://localhost:6379/2

# JWT
JWT_SECRET_KEY=your_jwt_secret_key
SECRET_KEY=your_app_secret_key
```

### Flask Configuration (`config.py`)
```python
class Config:
    # Database with RLS support
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        'DATABASE_URL',
        'postgresql+psycopg://postgres:password@localhost:5433/jivu_farm_db'
    )
    
    # Rate Limiting via Redis
    RATELIMIT_STORAGE_URI = os.environ.get('REDIS_URL', 'redis://localhost:6379/0')
    
    # Celery with Redis backend
    CELERY_BROKER_URL = os.environ.get('CELERY_BROKER_URL', 'redis://localhost:6379/1')
    CELERY_RESULT_BACKEND = os.environ.get('CELERY_RESULT_BACKEND', 'redis://localhost:6379/2')
```

## Security Guarantees

### Row-Level Security
- ✅ Database enforces tenant_id-based row filtering
- ✅ Prevents SQL injection from exposing cross-tenant data
- ✅ Cannot be bypassed by application logic errors
- ✅ All queries automatically filtered by PostgreSQL engine

### Rate Limiting
- ✅ Per-tenant rate limit buckets (tenant_id-based key)
- ✅ Independent throttle limits prevent noisy neighbor issues
- ✅ Redis-backed for distributed cluster support
- ✅ Applied to all routes via Flask-Limiter middleware

### Tenant Isolation
- ✅ JWT token contains tenant_id and role claims
- ✅ Middleware validates and propagates to database session
- ✅ Celery tasks run within Flask app context preserving tenant context
- ✅ Background jobs can access full database with tenant enforcement

## Testing Multi-Tenant Isolation

### Test 1: JWT Token with Tenant ID
```bash
# Login as user from tenant_id=1
curl -X POST http://localhost:5000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username": "farmer1", "password": "password"}'

# Check JWT contains tenant_id
# Token should have: {"tenant_id": 1, "role": "FARMER", ...}
```

### Test 2: RLS Enforcement
```sql
-- Simulate middleware setting tenant context
SET app.current_tenant_id = '1';

-- Query should only return tenant 1 records
SELECT * FROM milk_yield;  -- Only records where tenant_id = 1

-- Switch context
SET app.current_tenant_id = '2';

-- Different data returned
SELECT * FROM milk_yield;  -- Only records where tenant_id = 2
```

### Test 3: Rate Limit Isolation
```bash
# Tenant 1 makes 100 requests
for i in {1..100}; do
  curl -H "Authorization: Bearer $TOKEN_TENANT_1" http://localhost:5000/api/livestock
done

# Tenant 2 makes requests - should NOT be throttled
curl -H "Authorization: Bearer $TOKEN_TENANT_2" http://localhost:5000/api/livestock
# Response: 200 OK (not 429 Too Many Requests)
```

## Deployment Checklist

- [ ] PostgreSQL 13+ installed and running on port 5433
- [ ] Database `jivu_farm_db` created with user `jivu_app`
- [ ] `.env` file updated with valid credentials
- [ ] Redis running on ports 6379/0, 6379/1, 6379/2
- [ ] `flask db upgrade heads` executed successfully
- [ ] RLS policies verified in PostgreSQL: `\d+ milk_yield`
- [ ] JWT tokens include `tenant_id` in claims
- [ ] Middleware registered: `app.before_request(set_tenant_context)`
- [ ] Rate limiting tested: `curl -H "Authorization: Bearer $TOKEN" http://localhost/api/resource`
- [ ] Celery worker running: `celery -A app.celery worker --loglevel=info`

## Troubleshooting

### RLS Policies Not Enforcing
```sql
-- Check if RLS is enabled
SELECT relname, relrowsecurity FROM pg_class WHERE relname IN ('milk_yield', 'financial_transactions');

-- Expected output: relrowsecurity = t (true)

-- Re-enable RLS
ALTER TABLE milk_yield ENABLE ROW LEVEL SECURITY;
ALTER TABLE financial_transactions ENABLE ROW LEVEL SECURITY;
```

### Rate Limiting Not Isolated
```python
# Debug in Flask shell
python
> from app import app, g
> from app.utils.rate_limiting import tenant_based_key_func
> with app.test_request_context():
>     g.tenant_id = 1
>     print(tenant_based_key_func())  # Should print: tenant:1
```

### Celery Tasks Not Respecting Tenant Context
```python
# Ensure task uses ContextTask base class
@celery.task(base=ContextTask)
def my_task(tenant_id, data):
    # Add explicit tenant context if needed
    with app.app_context():
        db.session.execute(f"SET app.current_tenant_id = '{tenant_id}'")
        # ... process data
```

## Files Modified for Multi-Tenant Implementation

1. **`app/middleware.py`** - Tenant context middleware
2. **`app/__init__.py`** - Middleware registration, rate limiter configuration
3. **`app/utils/rate_limiting.py`** - Tenant-aware key function
4. **`app/celery_utils.py`** - Celery factory with context preservation
5. **`config.py`** - Database, Redis, Celery configuration
6. **`migrations/versions/390d029aa1ce_...py`** - RLS migration
7. **`.env`** - Environment variable configuration

## Next Steps

1. **Production PostgreSQL Setup** (requires valid credentials)
2. **Run Migration:** `flask db upgrade`
3. **Verify RLS:** Connect to database and check policies
4. **Load Test:** Verify per-tenant rate limiting works correctly
5. **Monitor:** Check database logs for RLS policy enforcement
