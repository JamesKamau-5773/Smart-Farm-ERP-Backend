from flask import jsonify
from flask_jwt_extended import create_access_token, set_access_cookies, unset_jwt_cookies
from app.repositories.user_repo import UserRepository

class AuthService:
    @staticmethod
    def authenticate_user(username, password):
        user = UserRepository.get_by_username(username)
        
        # 1. Verify User Exists and Password Matches
        if user and user.check_password(password):
            
            # 2. Check if account is locked/inactive
            if not user.is_active:
                return jsonify({"error": "Account is disabled. Contact Farm Administrator."}), 403
            
            # 3. Generate JWT with Identity and Role Claims
            access_token = create_access_token(
                identity=str(user.id), 
                additional_claims={"role": user.role}
            )
            
            # 4. Prepare Response Payload
            response = jsonify({
                "message": "Login successful",
                "user": {
                    "id": user.id,
                    "username": user.username,
                    "role": user.role
                }
            })
            
            # 5. Securely attach JWT to httpOnly cookies
            set_access_cookies(response, access_token)
            return response, 200
            
        return jsonify({"error": "Invalid username or password"}), 401

    @staticmethod
    def logout_user():
        response = jsonify({"message": "Logout successful"})
        unset_jwt_cookies(response)
        return response, 200