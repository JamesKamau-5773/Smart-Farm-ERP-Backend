from flask_jwt_extended import get_jwt_identity

from app.models.user import User
from app.repositories.user_repo import UserRepository
from app.utils.auth_errors import AuthError


def require_current_user() -> User:
    """The authenticated user for a ``@jwt_required()`` route."""
    user_id = get_jwt_identity()
    user = UserRepository.get_by_id(int(user_id)) if user_id else None
    if not user:
        raise AuthError('UNAUTHENTICATED', 'User not found.', 401)
    return user
