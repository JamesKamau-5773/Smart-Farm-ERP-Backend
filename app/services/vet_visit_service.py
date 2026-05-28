from datetime import date, datetime, timezone
from decimal import Decimal

from flask import jsonify

from app.repositories.cow_repo import CowRepository
from app.repositories.vet_visit_repo import VetVisitRepository


class VetVisitService:
    VALID_FOLLOW_UP_STATUSES = {'Not Required', 'Pending', 'Scheduled', 'Completed', 'Overdue', 'Cancelled'}

    @staticmethod
    def _normalize_medications(value):
        if value is None:
            return None
        if isinstance(value, list):
            return value
        if isinstance(value, str):
            cleaned = value.strip()
            if not cleaned:
                return None
            return [item.strip() for item in cleaned.split(',') if item.strip()]
        return value

    @staticmethod
    def _serialize_visit(visit):
        return {
            'id': visit.id,
            'animal_id': visit.animal_id,
            'cow_id': visit.animal_id,
            'vet_id': visit.vet_id,
            'visit_date': visit.visit_date.isoformat(),
            'reason_for_visit': visit.reason_for_visit,
            'diagnosis': visit.diagnosis,
            'medications': visit.medications or [],
            'recommendations': visit.recommendations,
            'remarks': visit.remarks,
            'observations': visit.observations,
            'follow_up_required': visit.follow_up_required,
            'follow_up_date': visit.follow_up_date.isoformat() if visit.follow_up_date else None,
            'follow_up_status': visit.follow_up_status,
            'follow_up_completed_at': visit.follow_up_completed_at.isoformat() if visit.follow_up_completed_at else None,
            'created_at': visit.created_at.isoformat() if visit.created_at else None,
        }

    @staticmethod
    def log_visit(tenant_id: int, vet_id: int, data: dict):
        animal_id = data.get('animal_id') or data.get('cow_id')
        visit_date_raw = data.get('visit_date')
        reason_for_visit = (data.get('reason_for_visit') or '').strip()

        if not animal_id or not visit_date_raw or not reason_for_visit:
            return jsonify({'error': 'animal_id, visit_date, and reason_for_visit are required.'}), 400

        try:
            animal_id = int(animal_id)
            visit_date = date.fromisoformat(str(visit_date_raw))
        except (TypeError, ValueError):
            return jsonify({'error': 'Invalid animal_id or visit_date format (YYYY-MM-DD).'}), 400

        livestock = CowRepository.get_by_id(animal_id)
        if not livestock:
            return jsonify({'error': 'Livestock not found in registry.'}), 404

        follow_up_required = bool(data.get('follow_up_required', False))
        follow_up_date_raw = data.get('follow_up_date')
        follow_up_date = None
        follow_up_status = 'Not Required'

        if follow_up_date_raw:
            try:
                follow_up_date = date.fromisoformat(str(follow_up_date_raw))
                follow_up_required = True
                follow_up_status = 'Scheduled'
            except (TypeError, ValueError):
                return jsonify({'error': 'follow_up_date must be in YYYY-MM-DD format.'}), 400
        elif follow_up_required:
            follow_up_status = 'Pending'

        medications = VetVisitService._normalize_medications(data.get('medications'))

        visit = VetVisitRepository.create(
            tenant_id=tenant_id,
            animal_id=animal_id,
            vet_id=vet_id,
            visit_date=visit_date,
            reason_for_visit=reason_for_visit,
            diagnosis=data.get('diagnosis'),
            medications=medications,
            recommendations=data.get('recommendations'),
            remarks=data.get('remarks'),
            observations=data.get('observations'),
            follow_up_required=follow_up_required,
            follow_up_date=follow_up_date,
            follow_up_status=follow_up_status,
        )

        return jsonify({'message': 'Vet visit recorded successfully.', 'visit': VetVisitService._serialize_visit(visit)}), 201

    @staticmethod
    def list_visits(tenant_id: int):
        visits = VetVisitRepository.list_by_tenant(tenant_id)
        return jsonify([VetVisitService._serialize_visit(visit) for visit in visits]), 200

    @staticmethod
    def schedule_follow_up(tenant_id: int, visit_id: int, data: dict):
        visit = VetVisitRepository.get_by_id_for_tenant(visit_id, tenant_id)
        if not visit:
            return jsonify({'error': 'Vet visit not found for this tenant.'}), 404

        follow_up_date_raw = data.get('follow_up_date')
        if not follow_up_date_raw:
            return jsonify({'error': 'follow_up_date is required.'}), 400

        try:
            follow_up_date = date.fromisoformat(str(follow_up_date_raw))
        except (TypeError, ValueError):
            return jsonify({'error': 'follow_up_date must be in YYYY-MM-DD format.'}), 400

        visit.follow_up_required = True
        visit.follow_up_date = follow_up_date
        visit.follow_up_status = 'Scheduled'
        VetVisitRepository.save()

        return jsonify({'message': 'Follow-up scheduled.', 'visit': VetVisitService._serialize_visit(visit)}), 200

    @staticmethod
    def complete_follow_up(tenant_id: int, visit_id: int, data: dict):
        visit = VetVisitRepository.get_by_id_for_tenant(visit_id, tenant_id)
        if not visit:
            return jsonify({'error': 'Vet visit not found for this tenant.'}), 404

        visit.follow_up_required = bool(data.get('follow_up_required', False))
        visit.follow_up_status = 'Completed'
        visit.follow_up_completed_at = datetime.now(timezone.utc)
        VetVisitRepository.save()

        return jsonify({'message': 'Follow-up marked as completed.', 'visit': VetVisitService._serialize_visit(visit)}), 200

    @staticmethod
    def list_pending_follow_ups(tenant_id: int):
        visits = VetVisitRepository.list_pending_follow_ups(tenant_id)
        return jsonify([VetVisitService._serialize_visit(visit) for visit in visits]), 200
