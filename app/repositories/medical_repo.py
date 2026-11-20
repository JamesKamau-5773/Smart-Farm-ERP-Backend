from app.models.livestock import MedicalRecord, Cow
from app import db
from sqlalchemy.exc import SQLAlchemyError
from app.services.audit_service import record_audit
from app.repositories.cow_repo import CowRepository

class MedicalRepository:
    @staticmethod
    def create_record(tenant_id: int, cow_id: int, vet_id: int, diagnosis: str, medication: str = None, withdrawal_days: int = 0, remarks: str = None) -> MedicalRecord:
        """Logs a clinical visit by a Veterinarian."""
        try:
            livestock_id = cow_id
            record = MedicalRecord(
                tenant_id=tenant_id,
                cow_id=livestock_id,
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
    def toggle_hardlock(tenant_id: int, cow_id: int, is_locked: bool, user_id: int, ip_address: str) -> Cow:
        """Allows the Farmer to isolate livestock's milk production."""
        try:
            livestock_id = cow_id
            livestock = CowRepository.get_by_id(livestock_id, tenant_id=tenant_id)
            if livestock:
                old_value = livestock.is_hardlocked
                livestock.is_hardlocked = is_locked
                
                record_audit(
                    user_id=user_id,
                    action='TOGGLE_HARDLOCK',
                    entity_type='Livestock',
                    entity_id=livestock.id,
                    old_value=old_value,
                    new_value=is_locked,
                    ip_address=ip_address
                )
                
                db.session.commit()
            return livestock
        except SQLAlchemyError as e:
            db.session.rollback()
            raise Exception("Failed, Database error while updating livestock status.")
    @staticmethod
    def list_with_withdrawal(cow_id: int, tenant_id: int) -> list[MedicalRecord]:
        """Treatments that carry a milk withdrawal period."""
        return MedicalRecord.query.filter(
            MedicalRecord.cow_id == cow_id,
            MedicalRecord.tenant_id == tenant_id,
            MedicalRecord.withdrawal_days_recommended > 0,
        ).all()

    @staticmethod
    def latest_for_cow(cow_id: int, tenant_id: int) -> MedicalRecord | None:
        return (
            MedicalRecord.query.filter_by(cow_id=cow_id, tenant_id=tenant_id)
            .order_by(MedicalRecord.visit_date.desc(), MedicalRecord.id.desc())
            .first()
        )
