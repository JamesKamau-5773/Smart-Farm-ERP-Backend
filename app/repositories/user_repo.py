from app.models.user import User
from app import db


class UserRepository:
    @staticmethod
    def get_by_username(username):
        return User.query.filter_by(username=username).first()

    @staticmethod
    def create_user(username, password, role):
        new_user = User(username=username,  role=role)
        new_user.set_password(password)
        db.session.add(new_user)
        db.session.commit()
        return new_user
