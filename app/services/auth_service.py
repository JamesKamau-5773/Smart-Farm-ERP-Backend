from flask import jsonify, make_response
from flask_jwt_extended import create_access_token, set_access_cookies
from app.repositories.user_repo import UserRepository

class AuthService:
    @staticmethod
    def authenticate_user(username, password):
        user = UserRepository.get_by_username(username)
        
        if user and user.check_password(password):
            if not user.is_active:
                return jsonify({"error": "Account is disabled"}), 403
            
            # Create the token with user identity and role
            access_token = create_access_token(identity=str(user.id), additional_claims={"role": user.role})
            
            response = jsonify({
                "message": "Login successful",
                "user": {
                    "username": user.username,
                    "role": user.role
                }
            })
            
            # Securely set the JWT in an httpOnly cookie
            set_access_cookies(response, access_token)
            return response, 200
            
        return jsonify({"error": "Invalid credentials"}), 401