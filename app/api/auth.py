# app/api/auth.py
from flask import Blueprint, request, jsonify
from app.services.auth_service import AuthService
from app import limiter

auth_bp = Blueprint('auth', __name__)


@auth_bp.route('/login', methods=['POST'])
@limiter.limit("5 per minute")  # Redis-backed throttling
def login():
    data = request.get_json()

    # AuthService will handle the JWT generation and cookie setting
    if not data or not data.get('username') or not data.get('password'):
        return jsonify({"error": "Username and password are required"}), 400
    return AuthService.authenticate_user(data['username'], data['password'])


@auth_bp.route('/logout', methods=['POST'])
def logout():
    response = jsonify({"message": "Logout successful"})

    # Clear JWT cookies
    from flask_jwt_extended import unset_jwt_cookies
    unset_jwt_cookies(response)
    return response, 200
