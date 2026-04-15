# app/api/auth.py
from flask import Blueprint, request, jsonify
from app.services.auth_service import AuthService
from app import limiter

auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/login', methods=['POST'])
@limiter.limit("5 per minute") # Redis-backed throttling
def login():
    data = request.get_json()
    # AuthService will handle the JWT generation and cookie setting
    return AuthService.authenticate_user(data['username'], data['password'])