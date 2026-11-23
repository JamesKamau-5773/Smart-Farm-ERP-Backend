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


def _postgres_database_uri(env_name: str, fallback: str, *, required_in_production: bool = True) -> str:
    """Return a synchronous PostgreSQL URL using the installed psycopg v3 driver.

    Managed PostgreSQL providers, including Render, commonly provide URLs that
    begin with ``postgresql://``. SQLAlchemy maps that bare scheme to psycopg2,
    while this application installs psycopg (v3). Make the driver explicit so
    provider-supplied URLs work without requiring a second PostgreSQL driver.
    """
    value = os.environ.get(env_name)
    production = os.environ.get('APP_ENV', 'development').lower() == 'production'
    if production and required_in_production and not value:
        raise RuntimeError(f'{env_name} must be set in production.')
    value = value or fallback
    parsed = make_url(value)
    if not parsed.drivername.startswith('postgresql'):
        raise RuntimeError(f"{env_name} must use a PostgreSQL URI.")
    return parsed.set(drivername='postgresql+psycopg').render_as_string(hide_password=False)

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
    # The HTTP bootstrap (POST /api/auth/register with role SUPER_ADMIN) is closed unless this is
    # True. Open it only to create the first super admin, then switch it off and remove the key.
    ALLOW_SUPER_ADMIN_BOOTSTRAP = os.environ.get('ALLOW_SUPER_ADMIN_BOOTSTRAP', 'False') == 'True'

    # Flask session cookie: only carries Authlib's OAuth state/nonce during the
    # Google redirect, which is a top-level navigation, so Lax is sufficient.
    SESSION_COOKIE_SECURE = JWT_COOKIE_SECURE
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'

    # Calendar dates for farm records (mixing, feeding) use the farm's local day.
    FARM_TIMEZONE = os.environ.get('FARM_TIMEZONE', 'Africa/Nairobi')

    # Authentication hardening
    FRONTEND_BASE_URL = os.environ.get('FRONTEND_BASE_URL', 'http://localhost:5173')
    # HMAC key for one-time codes and tokens; kept out of the database.
    AUTH_CODE_PEPPER = _required_secret('AUTH_CODE_PEPPER', 'dev-auth-code-pepper-not-for-production-use')
    AUTH_CHALLENGE_TTL_SECONDS = int(os.environ.get('AUTH_CHALLENGE_TTL_SECONDS', 600))
    AUTH_CHALLENGE_MAX_ATTEMPTS = int(os.environ.get('AUTH_CHALLENGE_MAX_ATTEMPTS', 5))

    # Platform admin (SUPER_ADMIN) sessions and two-factor authentication (TOTP).
    # Fernet keys (comma-separated, newest first) that encrypt TOTP secrets at rest. Generate one with
    # python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())".
    # Without a key the 2FA endpoints answer 503 and the super admin cannot finish signing in.
    MFA_ENCRYPTION_KEYS = os.environ.get('MFA_ENCRYPTION_KEYS', '')
    MFA_ISSUER = os.environ.get('MFA_ISSUER', 'Maziwa Smart')
    # Before 2FA the super admin's token lasts this long and can only complete 2FA or log out.
    PLATFORM_ADMIN_PENDING_MFA_MINUTES = int(os.environ.get('PLATFORM_ADMIN_PENDING_MFA_MINUTES', 10))
    # After 2FA. There are no refresh tokens: the super admin signs in again when it ends.
    PLATFORM_ADMIN_SESSION_MINUTES = int(os.environ.get('PLATFORM_ADMIN_SESSION_MINUTES', 30))

    # Google sign-in (OAuth 2.0 / OpenID Connect via Authlib)
    GOOGLE_CLIENT_ID = os.environ.get('GOOGLE_CLIENT_ID')
    GOOGLE_CLIENT_SECRET = os.environ.get('GOOGLE_CLIENT_SECRET')
    # Must exactly match an authorised redirect URI in Google Cloud Console.
    GOOGLE_REDIRECT_URI = os.environ.get('GOOGLE_REDIRECT_URI')

    # Transactional email (Resend)
    RESEND_API_KEY = os.environ.get('RESEND_API_KEY')
    EMAIL_FROM = os.environ.get('EMAIL_FROM')
    AUTH_EMAIL_ASYNC = os.environ.get('AUTH_EMAIL_ASYNC', str(APP_ENV == 'production')) == 'True'

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

    # Headers holding the visitor's IP, set by a proxy we trust (app/utils/client_ip.py).
    # Production runs on Render behind Cloudflare, which overwrites both headers; set
    # CLIENT_IP_HEADERS= (empty) for a production server reachable without that proxy.
    CLIENT_IP_HEADERS = tuple(
        header.strip()
        for header in os.environ.get(
            'CLIENT_IP_HEADERS',
            'True-Client-IP,CF-Connecting-IP' if APP_ENV == 'production' else '',
        ).split(',')
        if header.strip()
    )

    SQLALCHEMY_DATABASE_URI = _postgres_database_uri(
        'DATABASE_URL',
        'postgresql+psycopg://postgres:password@localhost:5433/jivu_farm_db',
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    MAX_CONTENT_LENGTH = int(os.environ.get('MAX_CONTENT_LENGTH', 5 * 1024 * 1024))

    # Uploaded file storage (certificates, animal photos, etc.)
    UPLOAD_ROOT = os.environ.get('UPLOAD_ROOT', os.path.join(_BACKEND_ROOT, 'instance', 'uploads'))
    # Where uploads are kept (app/services/media_storage.py): 'cloudinary' when CLOUDINARY_URL
    # (cloudinary://API_KEY:API_SECRET@CLOUD_NAME) is set, as on Render, whose own disk is wiped on
    # every deploy; 'local' (UPLOAD_ROOT) otherwise. MEDIA_STORAGE overrides the choice.
    CLOUDINARY_URL = os.environ.get('CLOUDINARY_URL') or None
    MEDIA_STORAGE = (os.environ.get('MEDIA_STORAGE') or ('cloudinary' if CLOUDINARY_URL else 'local')).strip().lower()
    # Top-level Cloudinary folder, so this app's files stay apart from anything else in the account.
    CLOUDINARY_FOLDER = os.environ.get('CLOUDINARY_FOLDER', 'maziwa')

    # Public demo account ("Try the live demo"). Off unless explicitly enabled;
    # when off, POST /api/auth/demo returns 404.
    DEMO_ENABLED = os.environ.get('DEMO_ENABLED', 'False') == 'True'
    # Demo sessions are short and cannot be refreshed (there are no refresh tokens).
    DEMO_SESSION_MINUTES = int(os.environ.get('DEMO_SESSION_MINUTES', 45))
    # Per-IP limits on starting a demo session (flask-limiter syntax, ';' separated).
    DEMO_LOGIN_RATE_LIMIT = os.environ.get('DEMO_LOGIN_RATE_LIMIT', '5 per minute;20 per hour')

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
    # Public E.164 number users send reverse-OTP codes to (e.g. +254700000000).
    WHATSAPP_BUSINESS_NUMBER = os.environ.get('WHATSAPP_BUSINESS_NUMBER')
    # Development only: log outbound WhatsApp messages instead of sending them.
    WHATSAPP_DRY_RUN = APP_ENV != 'production' and os.environ.get('WHATSAPP_DRY_RUN', 'False') == 'True'


class TestConfig(Config):
    TESTING = True
    SECRET_KEY = 'test-secret-key-that-is-at-least-thirty-two-characters'
    JWT_SECRET_KEY = 'test-jwt-secret-key-that-is-at-least-thirty-two-characters'
    # This class body runs on every import of config, production included, where no
    # test database exists; only the tests themselves need it.
    SQLALCHEMY_DATABASE_URI = _postgres_database_uri(
        'TEST_DATABASE_URL',
        'postgresql+psycopg://postgres:password@localhost:5433/jivu_farm_db_test',
        required_in_production=False,
    )
    RATELIMIT_STORAGE_URI = 'memory://'
    # Tests set REMOTE_ADDR directly; tests/test_client_ip.py enables the headers itself.
    CLIENT_IP_HEADERS = ()
    WTF_CSRF_ENABLED = False
    JWT_COOKIE_CSRF_PROTECT = False
    AUTH_CODE_PEPPER = 'test-auth-code-pepper-that-is-at-least-thirty-two-characters'
    # Test-only Fernet key for TOTP secrets.
    MFA_ENCRYPTION_KEYS = 'AcmfC5XyLBL-eVB3mQlJGmTVX6QprfLZhK0odfXfeEU='
    AUTH_EMAIL_ASYNC = False
    FRONTEND_BASE_URL = 'https://app.example.test'
    # Isolated from the real instance/uploads tree so test runs never write/delete real files.
    UPLOAD_ROOT = os.environ.get('TEST_UPLOAD_ROOT', tempfile.mkdtemp(prefix='jivu_test_uploads_'))
    # Tests never reach Cloudinary; the Cloudinary path is tested with the SDK mocked.
    CLOUDINARY_URL = None
    MEDIA_STORAGE = 'local'
