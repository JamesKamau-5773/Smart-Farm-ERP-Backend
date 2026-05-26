from datetime import date

from sqlalchemy.exc import SQLAlchemyError

from app import db
from app.models.livestock import VetVisit


class VetVisitRepository:
    @staticmethod
    def create(*, tenant_id: int, animal_id: int, vet_id: int, visit_date: date, reason_for_visit: str, diagnosis: str = None, medications=None, recommendations: str = None, remarks: str = None, observations: str = None, follow_up_required: bool = False, follow_up_date=None, follow_up_status: str = 'Not Required', follow_up_completed_at=None) -> VetVisit:
        try:
            visit = VetVisit(
                tenant_id=tenant_id,
                animal_id=animal_id,
                vet_id=vet_id,
                visit_date=visit_date,
                reason_for_visit=reason_for_visit,
                diagnosis=diagnosis,
                medications=medications,
                recommendations=recommendations,
                remarks=remarks,
                observations=observations,
                follow_up_required=follow_up_required,
                follow_up_date=follow_up_date,
                follow_up_status=follow_up_status,
                follow_up_completed_at=follow_up_completed_at,
            )
            db.session.add(visit)
            db.session.commit()
            return visit
        except SQLAlchemyError:
            db.session.rollback()
            raise Exception('Failed, Database error while saving vet visit.')

    @staticmethod
    def get_by_id_for_tenant(visit_id: int, tenant_id: int) -> VetVisit:
        return VetVisit.query.filter_by(id=visit_id, tenant_id=tenant_id).first()

    @staticmethod
    def list_by_tenant(tenant_id: int) -> list:
        return VetVisit.query.filter_by(tenant_id=tenant_id).order_by(VetVisit.visit_date.desc(), VetVisit.id.desc()).all()

    @staticmethod
    def list_pending_follow_ups(tenant_id: int) -> list:
        return VetVisit.query.filter(
            VetVisit.tenant_id == tenant_id,
            VetVisit.follow_up_required.is_(True),
            VetVisit.follow_up_status.in_(['Pending', 'Scheduled', 'Overdue']),
        ).order_by(VetVisit.follow_up_date.asc().nulls_last(), VetVisit.id.desc()).all()

    @staticmethod
    def save() -> None:
        try:
            db.session.commit()
        except SQLAlchemyError:
            db.session.rollback()
            raise Exception('Failed, Database error while updating vet visit.')
