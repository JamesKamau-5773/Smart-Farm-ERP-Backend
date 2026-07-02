import os
from datetime import timedelta
from dotenv import load_dotenv
from sqlalchemy.engine import make_url

load_dotenv()


def _secret_or_fallback(env_name: str, fallback: str, min_length: int = 32) -> str:
    value = os.environ.get(env_name) or fallback
    if len(value) < min_length:
        value = (value + fallback * 2)[:min_length]
    return value


def _postgres_database_uri(env_name: str, fallback: str) -> str:
    value = os.environ.get(env_name) or fallback
    parsed = make_url(value)
    if not parsed.drivername.startswith('postgresql'):
        raise RuntimeError(f"{env_name} must use a PostgreSQL URI.")
    return value

class Config:
    try:
        SECRET_KEY = _secret_or_fallback('SECRET_KEY', 'dev-secret-key-991-super-long')
        JWT_SECRET_KEY = _secret_or_fallback('JWT_SECRET_KEY', 'jwt-mgmt-7734-super-long-secret-key')
    except KeyError as e:
        raise RuntimeError(f"CRITICAL: Missing environment variable {e}")
    
    # Security & JWT
    
    JWT_TOKEN_LOCATION = ['cookies', 'headers']
    JWT_COOKIE_SECURE = os.environ.get('JWT_COOKIE_SECURE', 'False') == 'True'  # Enforce True in Production (HTTPS)
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(hours=2)
    JWT_COOKIE_CSRF_PROTECT = True
    JWT_CSRF_IN_COOKIES = True
    BOOTSTRAP_SUPER_ADMIN_KEY = os.environ.get('BOOTSTRAP_SUPER_ADMIN_KEY', '')
    
    SQLALCHEMY_DATABASE_URI = _postgres_database_uri(
        'DATABASE_URL',
        'postgresql+psycopg://postgres:password@localhost:5433/jivu_farm_db',
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Rate Limiting
    RATELIMIT_STORAGE_URI = os.environ.get('REDIS_URL','redis://localhost:6379/0')
    RATELIMIT_HEADERS_ENABLED = True

    # Celery
    CELERY_BROKER_URL = os.environ.get('CELERY_BROKER_URL', 'redis://localhost:6379/1')
    CELERY_RESULT_BACKEND = os.environ.get('CELERY_RESULT_BACKEND', 'redis://localhost:6379/2')

    # --- ERP SPECIFIC ---
    # Ensure all numbers are handled with precision (MoE Compliance)
    JSON_SORT_KEYS = False

   
    
    # M-Pesa Configuration
    MPESA_ENVIRONMENT = os.environ.get('MPESA_ENVIRONMENT', 'sandbox')
    MPESA_CONSUMER_KEY = os.environ.get('MPESA_CONSUMER_KEY')
    MPESA_CONSUMER_SECRET = os.environ.get('MPESA_CONSUMER_SECRET')
    MPESA_BUSINESS_SHORTCODE = os.environ.get('MPESA_BUSINESS_SHORTCODE')
    MPESA_PASSKEY = os.environ.get('MPESA_PASSKEY')
    MPESA_CALLBACK_URL = os.environ.get('MPESA_CALLBACK_URL')


class TestConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = _postgres_database_uri(
        'TEST_DATABASE_URL',
        'postgresql+psycopg://postgres:password@localhost:5433/jivu_farm_db_test',
    )
    RATELIMIT_STORAGE_URI = 'memory://'
    WTF_CSRF_ENABLED = False
    JWT_COOKIE_CSRF_PROTECT = False
