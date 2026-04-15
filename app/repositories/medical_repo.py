from app.models.livestock import MedicalRecord, Cow
from app import db
from sqlalchemy.exc import SQLAlchemyError

class MedicalRepository:
    @staticmethod
    def create_record(cow_id: int, vet_id: int, diagnosis: str, medication: str = None, withdrawal_days: int = 0, remarks: str = None) -> MedicalRecord:
        """Logs a clinical visit by a Veterinarian."""
        try:
            record = MedicalRecord(
                cow_id=cow_id,
                vet_id=vet_id,
                diagnosis=diagnosis,
                medication=medication,
                withdrawal_days_recommended=withdrawal_days,
                remarks=remarks
            )
            db.session.add(record)
            db.session.commit()
            return record
        except SQLAlchemyError as e:
            db.session.rollback()
            raise Exception("Failed, Database error while saving medical record.")

    @staticmethod
    def toggle_hardlock(cow_id: int, is_locked: bool) -> Cow:
        """Allows the Farmer to isolate a cow's milk production."""
        try:
            cow = Cow.query.get(cow_id)
            if cow:
                cow.is_hardlocked = is_locked
                db.session.commit()
            return cow
        except SQLAlchemyError as e:
            db.session.rollback()
            raise Exception("Failed, Database error while updating cow status.")