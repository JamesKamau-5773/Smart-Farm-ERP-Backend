# Smart Farm ERP System - Backend

This is the backend for the Jivu Smart Farm ERP, a comprehensive system designed to streamline dairy farm operations. It is built with Flask and provides a robust API for managing livestock, clinical records, finances, and daily operations.

## Features

- **Role-Based Access Control**: Differentiated access for `FARMER`, `FARM_HAND`, `VET`, and `CUSTOMER` roles using JWT.
- **Livestock Management**: Register and track individual cows.
- **Clinical Records**: Log veterinary visits and manage milk withdrawal periods with a `hardlock` feature.
- **Financial Management**: Record transactions, calculate daily unit production costs, and integrate with M-Pesa for billing.
- **Operational Logging**: Track daily milk production for each cow: who milked and who entered each record,
  how it arrived (app, WhatsApp, import), and its change against the cow's 7-day average for the same
  session, using the same rule that raises milk-drop alerts (corrected records are judged again). Calf feedings are logged against the day's milk, with litre totals.
- **Global Audit Trail**: Immutable logs for critical actions like financial transactions and security-sensitive changes.
- **Centralized Error Handling**: Graceful and consistent error responses across the API.
- **Database Backups**: Automated point-in-time backups for the PostgreSQL database using `pg_dump`.

## Tech Stack

- **Framework**: Flask
- **Database**: PostgreSQL (running in Docker)
- **Authentication**: JWT (JSON Web Tokens) with `Flask-JWT-Extended`
- **ORM**: SQLAlchemy with `Flask-SQLAlchemy`
- **Database Migrations**: `Flask-Migrate` (using Alembic)
- **Testing**: `unittest`
- **Containerization**: Docker

## Prerequisites

- Python 3.8+
- Docker and Docker Compose
- `pip` and `venv`

## Quick Start with Docker

Runs PostgreSQL, Redis, the API, the Celery worker and the frontend dev server together. You need Docker with Compose v2, and the frontend checked out next to this repo at `../frontend/jivu-frontend`.

```bash
cp .env.example .env          # optional: add M-Pesa / WhatsApp keys
docker compose up --build     # first run; later just `docker compose up`
```

- App: http://localhost:5173
- API: http://localhost:5000/api (health check: http://localhost:5000/health)
- PostgreSQL (for `psql` or restoring dumps): `localhost:55432`, database/user `maziwa`, password `maziwa-dev`

Migrations run automatically when the backend container starts. Data is kept in named volumes; `docker compose down` keeps it, `docker compose down -v` deletes it.

**Ports in use?** If something else already uses a port (for example a local Vite server on 5173), pick others:

```bash
FRONTEND_PORT=5174 BACKEND_PORT=5001 docker compose up
```

**Environment.** `docker-compose.yml` sets the database, Redis, Celery and CORS settings. Everything else (JWT secrets, M-Pesa, WhatsApp) comes from `.env` if present; see `.env.example`. Secrets are never copied into the image.

**Loading an existing dump** into a fresh stack:

```bash
docker compose up -d db
docker compose exec -T db psql -U maziwa -d maziwa < full_clean_dump.sql
docker compose up
```

**Running the tests** in the container:

```bash
docker compose exec db psql -U maziwa -d maziwa -c "CREATE DATABASE maziwa_test"
docker compose run --rm --no-deps -e APP_ENV=testing \
  -e TEST_DATABASE_URL=postgresql://maziwa:maziwa-dev@db:5432/maziwa_test \
  backend python -m pytest -q tests
```

**The image on its own.** `Dockerfile` builds one image for both the web server and the worker (Python 3.13, non-root user, health check on `/health`):

```bash
docker build -t maziwa-backend .
docker run --env-file .env -p 10000:10000 maziwa-backend                                    # web (runs migrations, then gunicorn)
docker run --env-file .env maziwa-backend celery -A celery_worker.celery worker --loglevel=info  # worker
```

## Getting Started

### 1. Clone the Repository

```bash
git clone <your-repository-url>
cd smart-farm-erp-system/backend
```

### 2. Set Up the Environment

Create and activate a Python virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Install the required dependencies:

```bash
pip install -r requirements.txt
```

### 3. Configure Environment Variables

Create a `.env` file in the `backend` directory:

```
FLASK_APP=run.py
FLASK_ENV=development
SECRET_KEY=a-strong-and-secret-key
JWT_SECRET_KEY=another-strong-and-secret-key
DATABASE_URL=postgresql+psycopg://postgres:password@localhost:5433/jivu_farm_db
TEST_DATABASE_URL=postgresql+psycopg://postgres:password@localhost:5433/jivu_farm_db_test
REDIS_URL=redis://localhost:6379/0

# M-Pesa Sandbox Credentials
MPESA_CONSUMER_KEY=your_daraja_consumer_key
MPESA_CONSUMER_SECRET=your_daraja_consumer_secret
MPESA_BUSINESS_SHORTCODE=174379
MPESA_PASSKEY=your_mpesa_passkey
MPESA_CALLBACK_URL=https://your-ngrok-url/api/finance/mpesa/callback
```

**Note**: You will need to replace the placeholder values with your actual credentials, especially for the M-Pesa integration.

### 4. Start the Database

If you have a `docker-compose.yml` file for your PostgreSQL instance, you can start it with:

```bash
docker-compose up -d
```

Otherwise, ensure your PostgreSQL server is running and accessible at the URI specified in `DATABASE_URL`.

### 5. Run Database Migrations

Apply the database schema to your database:

```bash
flask db upgrade heads
```

Run this again after pulling changes that add a migration. If the code is newer than the database,
requests fail with errors such as `column milk_logs.milker_employee_id does not exist`.

### 6. Run the Application

Start the Flask development server:

```bash
flask run
```

The application will be available at `http://127.0.0.1:5000`.

### Deploying to Render

The included `render.yaml` uses `scripts/start_web.sh` as the web-service start
command. The script runs `flask --app run:app db upgrade` before Gunicorn starts,
so the database schema is present before Render performs its first health check.

For an existing Render service, set its **Start Command** to:

```bash
./scripts/start_web.sh
```

Set `DATABASE_URL` to the Render PostgreSQL **internal** connection string and
set `APP_ENV=production`, `SECRET_KEY`, and `JWT_SECRET_KEY`. Then deploy again.


#### Moving the Render service to Docker

`render.yaml` still uses Render's Python runtime. Render services generally can't switch runtime in place, so move to the Dockerfile with a new service rather than editing the live one:

1. In Render, create a new **Web Service** from this repo with **Docker** as the runtime (Dockerfile path `./Dockerfile`, health check path `/health`).
2. Copy the environment variables from the current service (`DATABASE_URL`, `SECRET_KEY`, `JWT_SECRET_KEY`, M-Pesa, WhatsApp, `CORS_ALLOWED_ORIGINS`, `APP_ENV=production`). Render sets `PORT`; the image's start script uses it.
3. Deploy, check `/health` and log in from the frontend against the new URL.
4. Point the API domain (or the frontend's `VITE_API_BASE_URL`) at the new service, then retire the old one.
5. Replace the service block in `render.yaml` with:

   ```yaml
   - type: web
     name: smart-farm-erp-backend
     runtime: docker
     dockerfilePath: ./Dockerfile
     healthCheckPath: /health
   ```

The Celery worker isn't deployed on Render today. To run background tasks there, add a **Background Worker** from the same image with the command `celery -A celery_worker.celery worker --loglevel=info` and the same environment variables (plus `CELERY_BROKER_URL`/`CELERY_RESULT_BACKEND` pointing at a Redis instance).

## Running Tests

To run the test suite, execute the following command from the `backend` directory:

```bash
python -m unittest discover -s tests
```

The tests run against a separate PostgreSQL database defined by `TEST_DATABASE_URL` to avoid interfering with your development data.

## Database Backups

A backup script is provided at `scripts/backup_db.sh`. It leverages `pg_dump` to create non-locking, point-in-time backups of the database.

### How to Run

1.  Make the script executable:
    ```bash
    chmod +x scripts/backup_db.sh
    ```
2.  Run the script:
    ```bash
    ./scripts/backup_db.sh
    ```

Backups are stored in the `scripts/backups/` directory and files older than 7 days are automatically pruned.

## API Endpoints

A high-level overview of the available API endpoints:

- `POST /api/auth/register`: Register a new user.
- `POST /api/auth/login`: Log in to get a JWT.
- `POST /api/auth/logout`: Log out and invalidate the token.

- `POST /api/operations/cows`: Add a new cow.
- `POST /api/operations/cows/<id>/milk`: Record milk production.
- `GET|POST /api/production/yield`, `GET|PATCH|DELETE /api/production/yield/<id>`: Milk records. Rows carry
  `milker_name`, `recorded_by_name`, `recorded_via`, `vs_avg_litres` and `significant_drop`; `POST` and `PATCH`
  take an optional `milker_id` (an employee).
- `GET|POST /api/production/milk-dispositions`: Calf feedings, with `count` and `total_liters`.

- `POST /api/clinical/cows/<id>/medical`: Log a vet visit (VET only).
- `PUT /api/clinical/cows/<id>/hardlock`: Lock/unlock a cow's milk for sale (FARMER only).

- `GET /api/finance/unit-cost`: Calculate the daily cost per liter of milk.
- `POST /api/finance/billing/stk-push`: Initiate an M-Pesa payment.
- `POST /api/finance/mpesa/callback`: Webhook for M-Pesa to post transaction status.

## Frontend Integration

The frontend contract should use the backend as the source of truth for auth, tenant/farm context, and server-side calculations. See [backend-endpoint-map.md](backend-endpoint-map.md) for the current endpoint map and the HR gaps the frontend must not assume yet.
