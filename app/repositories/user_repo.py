from app.models.user import User
from app import db
from sqlalchemy.exc import SQLAlchemyError


class UserRepository:
    @staticmethod
    def get_by_username(username: str) -> User:
        """Fetches a user by their exact username."""
        return User.query.filter_by(username=username).first()

    @staticmethod
    def get_by_id(user_id: int) -> User:
        """Fetches a user by their primary key."""
        return User.query.get(user_id)

    @staticmethod
    def create_user(username: str, email: str, password: str, role: str) -> User:
        """Creates a new user with a hashed password and saves to DB."""
        try:
            new_user = User(username=username, email=email, role=role)
            new_user.set_password(password)
            db.session.add(new_user)
            db.session.commit()
            return new_user
        except SQLAlchemyError as e:
            db.session.rollback()
            # In production, log this exception
            raise Exception("Database error occurred while creating user.")
