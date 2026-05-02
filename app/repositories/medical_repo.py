from app.models.livestock import MedicalRecord, Cow
from app import db
from sqlalchemy.exc import SQLAlchemyError
from app.services.audit_service import record_audit

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
    def toggle_hardlock(cow_id: int, is_locked: bool, user_id: int, ip_address: str) -> Cow:
        """Allows the Farmer to isolate a cow's milk production."""
        try:
            cow = Cow.query.get(cow_id)
            if cow:
                old_value = cow.is_hardlocked
                cow.is_hardlocked = is_locked
                
                record_audit(
                    user_id=user_id,
                    action='TOGGLE_HARDLOCK',
                    entity_type='Cow',
                    entity_id=cow.id,
                    old_value=old_value,
                    new_value=is_locked,
                    ip_address=ip_address
                )
                
                db.session.commit()
            return cow
        except SQLAlchemyError as e:
            db.session.rollback()
            raise Exception("Failed, Database error while updating cow status.")