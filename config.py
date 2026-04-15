import os
from datetime import timedelta
from dotenv import load_dotenv

load_dotenv()

class Config:
    try:
        SECRET_KEY = os.environ['SECRET_KEY']
        JWT_SECRET_KEY = os.environ['JWT_SECRET_KEY']
    except KeyError as e:
        raise RuntimeError(f"CRITICAL: Missing environment variable {e}")
    
    # Security & JWT
    
    JWT_TOKEN_LOCATION = ['cookies']
    JWT_COOKIE_SECURE = os.environ.get('JWT_COOKIE_SECURE', 'False') == 'True'  # Enforce True in Production (HTTPS)
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(hours=2)
    JWT_COOKIE_CSRF_PROTECT = True
    JWT_CSRF_IN_COOKIES = True
    
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        'DATABASE_URL', 
        'postgresql://postgres:password@localhost:5433/jivu_farm_db'
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    # Rate Limiting
    RATELIMIT_STORAGE_URI = os.environ.get('REDIS_URL','redis://localhost:6379/0')
    RATELIMIT_HEADERS_ENABLED = True

    # --- ERP SPECIFIC ---
    # Ensure all numbers are handled with precision (MoE Compliance)
    JSON_SORT_KEYS = False