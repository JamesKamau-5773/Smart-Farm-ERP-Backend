import os
import tempfile
from datetime import timedelta
from dotenv import load_dotenv
from sqlalchemy.engine import make_url

load_dotenv()

_BACKEND_ROOT = os.path.dirname(os.path.abspath(__file__))


def _required_secret(env_name: str, fallback: str, min_length: int = 32) -> str:
    value = os.environ.get(env_name)
    production = os.environ.get('APP_ENV', 'development').lower() == 'production'
    if production and (not value or value == fallback or len(value) < min_length):
        raise RuntimeError(f'{env_name} must be set to a unique value of at least {min_length} characters in production.')
    return value or fallback


def _postgres_database_uri(env_name: str, fallback: str) -> str:
    value = os.environ.get(env_name)
    if os.environ.get('APP_ENV', 'development').lower() == 'production' and not value:
        raise RuntimeError(f'{env_name} must be set in production.')
    value = value or fallback
    parsed = make_url(value)
    if not parsed.drivername.startswith('postgresql'):
        raise RuntimeError(f"{env_name} must use a PostgreSQL URI.")
    return value

class Config:
    APP_ENV = os.environ.get('APP_ENV', 'development').lower()
    SECRET_KEY = _required_secret('SECRET_KEY', 'dev-secret-key-991-super-long')
    JWT_SECRET_KEY = _required_secret('JWT_SECRET_KEY', 'jwt-mgmt-7734-super-long-secret-key')

    # Security & JWT

    JWT_TOKEN_LOCATION = ['cookies', 'headers']
    JWT_COOKIE_SECURE = os.environ.get('JWT_COOKIE_SECURE', str(APP_ENV == 'production')) == 'True'
    JWT_COOKIE_HTTPONLY = True
    JWT_COOKIE_SAMESITE = os.environ.get('JWT_COOKIE_SAMESITE', 'Lax')
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(hours=2)
    JWT_COOKIE_CSRF_PROTECT = os.environ.get('JWT_COOKIE_CSRF_PROTECT', str(APP_ENV == 'production')) == 'True'
    JWT_CSRF_IN_COOKIES = True
    BOOTSTRAP_SUPER_ADMIN_KEY = os.environ.get('BOOTSTRAP_SUPER_ADMIN_KEY', '')

    # CORS: Whitelist of allowed origins for better security
    _DEFAULT_CORS_ORIGINS = ','.join((
        'http://localhost:5173',
        'http://localhost:5175',
        'http://localhost:4173',
        'http://127.0.0.1:5173',
        'http://127.0.0.1:5175',
        'http://127.0.0.1:4173',
    ))
    CORS_ALLOWED_ORIGINS = tuple(
        origin.strip()
        for origin in os.environ.get('CORS_ALLOWED_ORIGINS', _DEFAULT_CORS_ORIGINS).split(',')
        if origin.strip()
    )

    SQLALCHEMY_DATABASE_URI = _postgres_database_uri(
        'DATABASE_URL',
        'postgresql+psycopg://postgres:password@localhost:5433/jivu_farm_db',
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    MAX_CONTENT_LENGTH = int(os.environ.get('MAX_CONTENT_LENGTH', 5 * 1024 * 1024))

    # Uploaded file storage (certificates, animal photos, etc.)
    UPLOAD_ROOT = os.environ.get('UPLOAD_ROOT', os.path.join(_BACKEND_ROOT, 'instance', 'uploads'))

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

    # WhatsApp Cloud API Configuration (Meta)
    WHATSAPP_APP_SECRET = os.environ.get('WHATSAPP_APP_SECRET')
    WHATSAPP_VERIFY_TOKEN = os.environ.get('WHATSAPP_VERIFY_TOKEN')
    WHATSAPP_ACCESS_TOKEN = os.environ.get('WHATSAPP_ACCESS_TOKEN')
    WHATSAPP_PHONE_NUMBER_ID = os.environ.get('WHATSAPP_PHONE_NUMBER_ID')


class TestConfig(Config):
    TESTING = True
    SECRET_KEY = 'test-secret-key-that-is-at-least-thirty-two-characters'
    JWT_SECRET_KEY = 'test-jwt-secret-key-that-is-at-least-thirty-two-characters'
    SQLALCHEMY_DATABASE_URI = _postgres_database_uri(
        'TEST_DATABASE_URL',
        'postgresql+psycopg://postgres:password@localhost:5433/jivu_farm_db_test',
    )
    RATELIMIT_STORAGE_URI = 'memory://'
    WTF_CSRF_ENABLED = False
    JWT_COOKIE_CSRF_PROTECT = False
    # Isolated from the real instance/uploads tree so test runs never write/delete real files.
    UPLOAD_ROOT = os.environ.get('TEST_UPLOAD_ROOT', tempfile.mkdtemp(prefix='jivu_test_uploads_'))
