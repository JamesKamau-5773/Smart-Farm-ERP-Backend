from app.models.user import User
from app import db
from sqlalchemy import func, or_
from sqlalchemy.exc import SQLAlchemyError


class UserRepository:
    @staticmethod
    def get_by_username(username: str) -> User:
        """Fetches a user by their exact username."""
        return User.query.filter_by(username=username).first()

    @staticmethod
    def get_by_email(email: str) -> User:
        """Fetches a user by their exact email address."""
        return User.query.filter_by(email=email).first()

    @staticmethod
    def get_by_email_ci(email: str) -> User:
        """Fetches a user by email, ignoring case and surrounding whitespace."""
        normalized = (email or '').strip().lower()
        if not normalized:
            return None
        return User.query.filter(func.lower(User.email) == normalized).first()

    @staticmethod
    def get_by_phone(e164: str) -> User:
        """Fetches a user by their E.164 phone number."""
        if not e164:
            return None
        return User.query.filter_by(phone_number=e164).first()

    @staticmethod
    def get_by_username_ci(username: str) -> User:
        normalized = (username or '').strip().lower()
        if not normalized:
            return None
        return User.query.filter(func.lower(User.username) == normalized).first()

    @staticmethod
    def find_by_legacy_phone(candidates) -> User:
        """Matches accounts whose phone only lives in username/identifier
        (rows created before phone_number was populated)."""
        candidates = {candidate for candidate in candidates if candidate}
        if not candidates:
            return None
        return User.query.filter(
            or_(
                User.username.in_(candidates),
                User.identifier.in_({f'phone_{candidate}' for candidate in candidates}),
            )
        ).first()

    @staticmethod
    def get_by_id(user_id: int) -> User:
        """Fetches a user by their primary key."""
        return db.session.get(User, user_id)

    @staticmethod
    def create_user(username: str, password: str, role: str) -> User:
        """Creates a new user with a hashed password and saves to DB."""
        try:
            new_user = User(username=username, role=role)
            new_user.set_password(password)
            db.session.add(new_user)
            db.session.commit()
            return new_user
        except SQLAlchemyError as e:
            db.session.rollback()
            # In production, log this exception
            raise Exception("Database error occurred while creating user.")
