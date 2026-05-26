from app.models.livestock import Cow
from app import db
from sqlalchemy.exc import SQLAlchemyError

class CowRepository:
    @staticmethod
    def get_by_livestock_id(livestock_id: int) -> Cow:
        return db.session.get(Cow, livestock_id)

    @staticmethod
    def get_by_id(cow_id: int) -> Cow:
        return CowRepository.get_by_livestock_id(cow_id)

    @staticmethod
    def get_by_tag(tag_number: str) -> Cow:
        return Cow.query.filter_by(tag_number=tag_number).first()

    @staticmethod
    def get_all_active_livestock() -> list:
        return Cow.query.filter_by(is_active=True).all()

    @staticmethod
    def get_all_active() -> list:
        return CowRepository.get_all_active_livestock()

    @staticmethod
    def create_livestock(tag_number: str, date_of_birth, name: str = None, breed_status: str = "Foundation") -> Cow:
        try:
            new_livestock = Cow(
                tag_number=tag_number,
                name=name,
                breed_status=breed_status,
                date_of_birth=date_of_birth
            )
            db.session.add(new_livestock)
            db.session.commit()
            return new_livestock
        except SQLAlchemyError as e:
            db.session.rollback()
            raise Exception("Failed, Database error while registering cow.")

    @staticmethod
    def create_cow(tag_number: str, date_of_birth, name: str = None, breed_status: str = "Foundation") -> Cow:
        return CowRepository.create_livestock(tag_number, date_of_birth, name=name, breed_status=breed_status)