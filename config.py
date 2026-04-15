import os
from datetime import timedelta

class Config:
    # Security
    SECRET_KEY = os.environ.get('SECRET_KEY', 'jivu-super-secret-key')
    JWT_SECRET_KEY = os.environ.get('JWT_SECRET_KEY', 'jivu-jwt-secret')
    JWT_TOKEN_LOCATION = ['cookies']
    JWT_COOKIE_SECURE = False  # Set to True in Production
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(hours=2)
    JWT_COOKIE_CSRF_PROTECT = True
    JWT_CSRF_IN_COOKIES = True
    
    # Database (PostgreSQL 16 on Port 5433)
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        'DATABASE_URL', 
        'postgresql://postgres:password@localhost:5433/jivu_farm_db'
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    
    # Redis (Rate Limiting)
    RATELIMIT_STORAGE_URI = os.environ.get('REDIS_URL', 'redis://localhost:6379/0')