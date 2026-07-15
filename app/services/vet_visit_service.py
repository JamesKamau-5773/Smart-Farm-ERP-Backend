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

        livestock = CowRepository.get_by_id(animal_id, tenant_id=tenant_id)
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

    @staticmethod
    def update_visit(tenant_id: int, visit_id: int, data: dict):
        visit = VetVisitRepository.get_by_id_for_tenant(visit_id, tenant_id)
        if not visit:
            return jsonify({'error': 'Vet visit not found for this tenant.'}), 404

        animal_id = data.get('animal_id') or data.get('cow_id')
        if animal_id not in (None, ''):
            try:
                animal_id = int(animal_id)
            except (TypeError, ValueError):
                return jsonify({'error': 'Invalid animal_id format.'}), 400

            livestock = CowRepository.get_by_id(animal_id, tenant_id=tenant_id)
            if not livestock:
                return jsonify({'error': 'Livestock not found in registry.'}), 404
            visit.animal_id = animal_id

        visit_date_raw = data.get('visit_date')
        if visit_date_raw not in (None, ''):
            try:
                visit.visit_date = date.fromisoformat(str(visit_date_raw))
            except (TypeError, ValueError):
                return jsonify({'error': 'visit_date must be in YYYY-MM-DD format.'}), 400

        reason_for_visit = data.get('reason_for_visit')
        if reason_for_visit is not None:
            cleaned_reason = str(reason_for_visit).strip()
            if cleaned_reason:
                visit.reason_for_visit = cleaned_reason

        if 'diagnosis' in data:
            diagnosis = data.get('diagnosis')
            visit.diagnosis = diagnosis.strip() if isinstance(diagnosis, str) else diagnosis

        if 'medications' in data:
            visit.medications = VetVisitService._normalize_medications(data.get('medications'))

        if 'recommendations' in data:
            recommendations = data.get('recommendations')
            visit.recommendations = recommendations.strip() if isinstance(recommendations, str) else recommendations

        if 'remarks' in data:
            remarks = data.get('remarks')
            visit.remarks = remarks.strip() if isinstance(remarks, str) else remarks

        if 'observations' in data:
            observations = data.get('observations')
            visit.observations = observations.strip() if isinstance(observations, str) else observations

        follow_up_required = data.get('follow_up_required')
        if follow_up_required is not None:
            visit.follow_up_required = bool(follow_up_required)

        if 'follow_up_date' in data:
            follow_up_date_raw = data.get('follow_up_date')
            if follow_up_date_raw in (None, ''):
                visit.follow_up_date = None
                if not visit.follow_up_required:
                    visit.follow_up_status = 'Not Required'
            else:
                try:
                    visit.follow_up_date = date.fromisoformat(str(follow_up_date_raw))
                    visit.follow_up_required = True
                    if visit.follow_up_status == 'Not Required':
                        visit.follow_up_status = 'Scheduled'
                except (TypeError, ValueError):
                    return jsonify({'error': 'follow_up_date must be in YYYY-MM-DD format.'}), 400

        follow_up_status = data.get('follow_up_status')
        if follow_up_status is not None:
            cleaned_status = str(follow_up_status).strip()
            if cleaned_status and cleaned_status not in VetVisitService.VALID_FOLLOW_UP_STATUSES:
                return jsonify({'error': 'Invalid follow_up_status value.'}), 400
            if cleaned_status:
                visit.follow_up_status = cleaned_status

        if visit.follow_up_status == 'Completed' and visit.follow_up_completed_at is None:
            visit.follow_up_completed_at = datetime.now(timezone.utc)

        VetVisitRepository.save()
        return jsonify({'message': 'Vet visit updated successfully.', 'visit': VetVisitService._serialize_visit(visit)}), 200
