from app.models.livestock import Cow
from app import db
from sqlalchemy.exc import SQLAlchemyError

class CowRepository:
    @staticmethod
    def get_by_id(cow_id: int) -> Cow:
        return Cow.query.get(cow_id)

    @staticmethod
    def get_by_tag(tag_number: str) -> Cow:
        return Cow.query.filter_by(tag_number=tag_number).first()

    @staticmethod
    def get_all_active() -> list:
        return Cow.query.filter_by(is_active=True).all()

    @staticmethod
    def create_cow(tag_number: str, date_of_birth, name: str = None, breed_status: str = "Foundation") -> Cow:
        try:
            new_cow = Cow(
                tag_number=tag_number,
                name=name,
                breed_status=breed_status,
                date_of_birth=date_of_birth
            )
            db.session.add(new_cow)
            db.session.commit()
            return new_cow
        except SQLAlchemyError as e:
            db.session.rollback()
            raise Exception("Failed, Database error while registering cow.")