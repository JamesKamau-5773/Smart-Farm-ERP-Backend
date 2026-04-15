from flask import Blueprint, request, jsonify
from app.services.auth_service import AuthService
from app import limiter

auth_bp = Blueprint('auth', __name__)


@auth_bp.route('/login', methods=['POST'])
@limiter.limit("10 per 10 minutes")
@limiter.limit("5 per minute")  # Redis throttle: Max 10 attempts per IP
def login():
    data = request.get_json()

    # Input Validation
    if not data or not data.get('username') or not data.get('password'):
        return jsonify({"error": "Username and password are required"}), 400

    return AuthService.authenticate_user(data['username'], data['password'])


@auth_bp.route('/logout', methods=['POST'])
def logout():
    return AuthService.logout_user()


@auth_bp.route('/status', methods=['GET'])
# @jwt_required() # We will implement role decorators in the next sprint
def status():
    """A simple endpoint to verify if the server is responding to auth routes."""
    return jsonify({"status": "Auth Blueprint is active."}), 200
