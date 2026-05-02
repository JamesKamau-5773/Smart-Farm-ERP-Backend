# Smart Farm ERP System - Backend

This is the backend for the Jivu Smart Farm ERP, a comprehensive system designed to streamline dairy farm operations. It is built with Flask and provides a robust API for managing livestock, clinical records, finances, and daily operations.

## Features

- **Role-Based Access Control**: Differentiated access for `FARMER` and `VET` roles using JWT.
- **Livestock Management**: Register and track individual cows.
- **Clinical Records**: Log veterinary visits and manage milk withdrawal periods with a `hardlock` feature.
- **Financial Management**: Record transactions, calculate daily unit production costs, and integrate with M-Pesa for billing.
- **Operational Logging**: Track daily milk production for each cow.
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

Create a `.env` file in the `backend` directory. Use the `.env.example` as a template:

```
FLASK_APP=run.py
FLASK_ENV=development
SECRET_KEY=a-strong-and-secret-key
JWT_SECRET_KEY=another-strong-and-secret-key
DATABASE_URL=postgresql://postgres:password@localhost:5432/jivu_farm_db
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

Otherwise, ensure your PostgreSQL Docker container is running and accessible at the URI specified in `DATABASE_URL`.

### 5. Run Database Migrations

Apply the database schema to your database:

```bash
flask db upgrade
```

### 6. Run the Application

Start the Flask development server:

```bash
flask run
```

The application will be available at `http://127.0.0.1:5000`.

## Running Tests

To run the test suite, execute the following command from the `backend` directory:

```bash
python -m unittest discover -s tests
```

The tests run against a separate in-memory SQLite database to avoid interfering with your development data.

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

- `POST /api/clinical/cows/<id>/medical`: Log a vet visit (VET only).
- `PUT /api/clinical/cows/<id>/hardlock`: Lock/unlock a cow's milk for sale (FARMER only).

- `GET /api/finance/unit-cost`: Calculate the daily cost per liter of milk.
- `POST /api/finance/billing/stk-push`: Initiate an M-Pesa payment.
- `POST /api/finance/mpesa/callback`: Webhook for M-Pesa to post transaction status.
