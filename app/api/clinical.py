from __future__ import annotations
from flask import Blueprint, request, jsonify, current_app, g
from flask_jwt_extended import jwt_required, get_jwt_identity, get_jwt
from app.services.medical_service import MedicalService
from app.services.vet_visit_service import VetVisitService
from app.models.livestock import VetVisit, Cow, MedicalRecord
from app.models.supply import MilkLog
from app.models.user import User
from app import db
from app.utils.decorators import role_required
from app.models.user import Role
from app.utils.jwt_payload import parse_public_int_id

clinical_bp = Blueprint('clinical', __name__)
medical_alias_bp = Blueprint('medical_alias', __name__)
safety_bp = Blueprint('safety', __name__)
veterinary_bp = Blueprint('veterinary', __name__)


def _pagination_params():
    try:
        page = max(int(request.args.get('page', 1)), 1)
    except (TypeError, ValueError):
        page = 1
    try:
        per_page = int(request.args.get('per_page', 20))
    except (TypeError, ValueError):
        per_page = 20
    per_page = min(max(per_page, 1), 200)
    return page, per_page


def _get_tenant_id_from_claims():
    claims = get_jwt()
    tenant_public_id = claims.get('tenant_id')
    if not tenant_public_id:
        return None
    try:
        return parse_public_int_id(tenant_public_id, 'tenant_')
    except (TypeError, ValueError):
        return None


def _resolve_cow_id_for_tenant(tenant_id, data):
    raw_cow = data.get('cow_id') or data.get('animal_id') or data.get('cow')
    if raw_cow is None:
        return None

    cow_value = str(raw_cow).strip()
    if not cow_value:
        return None

    # Accept direct numeric ID first.
    try:
        return int(cow_value)
    except (TypeError, ValueError):
        pass

    # Fallback: treat value as tag number lookup (e.g., c-001/C-001/COW001).
    from app.repositories.cow_repo import CowRepository

    candidate_tags = [cow_value, cow_value.upper()]
    if len(cow_value) > 1 and cow_value[1] == '-':
        candidate_tags.extend([
            f"{cow_value[0].upper()}{cow_value[1:]}",
            f"{cow_value[0].lower()}{cow_value[1:]}",
        ])

    # Common typo correction for frontend values like c-oo1 -> c-001.
    normalized = cow_value.replace('o', '0').replace('O', '0')
    candidate_tags.extend([normalized, normalized.upper()])

    # If value looks like c-001, also try COW001 style tags used in some datasets.
    compact = normalized.replace('-', '').replace('_', '')
    if compact and compact[0].lower() == 'c' and compact[1:].isdigit():
        digits = compact[1:]
        candidate_tags.extend([
            f"COW{digits}",
            f"cow{digits}",
            f"C-{digits}",
            f"c-{digits}",
        ])

    for tag in dict.fromkeys(candidate_tags):
        cow = CowRepository.get_by_tag(tag, tenant_id=tenant_id)
        if cow:
            return cow.id

    # Frontend sometimes sends the animal display name in `cow`.
    cow_by_name = CowRepository.get_by_name(cow_value, tenant_id=tenant_id)
    if cow_by_name:
        return cow_by_name.id

    return None


def _normalize_vet_visit_payload(tenant_id, data):
    payload = dict(data or {})

    cow_id = _resolve_cow_id_for_tenant(tenant_id, payload)
    if cow_id is not None:
        payload['cow_id'] = cow_id
        payload['animal_id'] = cow_id

    visit_date = payload.get('visit_date') or payload.get('date')
    if visit_date is not None:
        payload['visit_date'] = visit_date

    reason = payload.get('reason_for_visit') or payload.get('reason')
    if reason is not None:
        payload['reason_for_visit'] = reason

    meds = payload.get('medications')
    if meds is None:
        meds = payload.get('meds')
    if meds is not None:
        payload['medications'] = meds

    follow_up_date = payload.get('follow_up_date') or payload.get('followUp')
    if follow_up_date is not None:
        payload['follow_up_date'] = follow_up_date

    if payload.get('follow_up_date') and 'follow_up_required' not in payload:
        payload['follow_up_required'] = True

    if payload.get('updatedBy') and not payload.get('remarks'):
        payload['remarks'] = f"Updated by {payload.get('updatedBy')}"

    if payload.get('cow') and not (payload.get('cow_id') or payload.get('animal_id')):
        payload['_cow_lookup_failed'] = True

    return payload

@clinical_bp.route('/cows/<int:cow_id>/medical', methods=['POST'])
@clinical_bp.route('/livestock/<int:cow_id>/medical', methods=['POST'])
@jwt_required()
@role_required(Role.VET)
def log_vet_visit(cow_id):
    """Only Veterinary Doctors can log clinical diagnoses."""
    tenant_id = _get_tenant_id_from_claims()
    if tenant_id is None:
        return jsonify({'error': 'Missing or invalid tenant in token.'}), 400
    vet_id = get_jwt_identity()
    data = request.get_json()
    return MedicalService.log_clinical_visit(tenant_id, cow_id, vet_id, data)

@clinical_bp.route('/cows/<int:cow_id>/hardlock', methods=['PUT'])
@clinical_bp.route('/livestock/<int:cow_id>/hardlock', methods=['PUT'])
@jwt_required()
@role_required(Role.FARMER)
def toggle_farmer_hardlock(cow_id):
    """Only Farmers can lock/unlock milk for commercial distribution."""
    tenant_id = _get_tenant_id_from_claims()
    if tenant_id is None:
        return jsonify({'error': 'Missing or invalid tenant in token.'}), 400
    data = request.get_json()
    
    if 'is_locked' not in data:
        return jsonify({"error": "is_locked boolean parameter is required."}), 400
        
    is_locked = bool(data.get('is_locked'))
    user_id = get_jwt_identity()
    ip_address = request.remote_addr
    return MedicalService.enforce_hardlock(tenant_id, cow_id, is_locked, user_id, ip_address)


@clinical_bp.route('/vet-visits', methods=['POST'])
@jwt_required()
@role_required(Role.VET, Role.FARMER)
def log_vet_visit_workflow():
    tenant_id = _get_tenant_id_from_claims()
    if tenant_id is None:
        return jsonify({'error': 'Missing or invalid tenant in token.'}), 400

    vet_id = get_jwt_identity()
    data = _normalize_vet_visit_payload(tenant_id, request.get_json() or {})
    if data.get('_cow_lookup_failed'):
        return jsonify({'error': 'Cow not found in tenant registry. Use cow_id or a valid cow tag.'}), 404
    return VetVisitService.log_visit(tenant_id, vet_id, data)


@clinical_bp.route('/vet-visits', methods=['GET'])
@jwt_required()
@role_required(Role.VET, Role.FARMER)
def list_vet_visits_workflow():
    tenant_id = _get_tenant_id_from_claims()
    if tenant_id is None:
        return jsonify({'error': 'Missing or invalid tenant in token.'}), 400

    return VetVisitService.list_visits(tenant_id)


@clinical_bp.route('/vet-visits/<int:visit_id>/follow-up/schedule', methods=['PUT'])
@jwt_required()
@role_required(Role.VET, Role.FARMER)
def schedule_vet_follow_up(visit_id):
    tenant_id = _get_tenant_id_from_claims()
    if tenant_id is None:
        return jsonify({'error': 'Missing or invalid tenant in token.'}), 400

    data = request.get_json() or {}
    return VetVisitService.schedule_follow_up(tenant_id, visit_id, data)


@clinical_bp.route('/vet-visits/<int:visit_id>/follow-up/complete', methods=['PUT'])
@jwt_required()
@role_required(Role.VET, Role.FARMER)
def complete_vet_follow_up(visit_id):
    tenant_id = _get_tenant_id_from_claims()
    if tenant_id is None:
        return jsonify({'error': 'Missing or invalid tenant in token.'}), 400

    data = request.get_json() or {}
    return VetVisitService.complete_follow_up(tenant_id, visit_id, data)


@clinical_bp.route('/vet-visits/follow-ups/pending', methods=['GET'])
@jwt_required()
@role_required(Role.VET, Role.FARMER)
def list_pending_vet_follow_ups():
    tenant_id = _get_tenant_id_from_claims()
    if tenant_id is None:
        return jsonify({'error': 'Missing or invalid tenant in token.'}), 400

    return VetVisitService.list_pending_follow_ups(tenant_id)


@medical_alias_bp.route('/api/medical/records', methods=['GET'])
@medical_alias_bp.route('/api/medical/records', methods=['POST'])
@jwt_required()
@role_required(Role.VET, Role.FARMER)
def medical_records_alias():
    if request.method == 'GET':
        return list_vet_visits_workflow()
    return log_vet_visit_workflow()


@medical_alias_bp.route('/api/medical/records/<int:visit_id>', methods=['PUT', 'PATCH'])
@jwt_required()
@role_required(Role.VET, Role.FARMER)
def medical_record_alias_update(visit_id):
    tenant_id = _get_tenant_id_from_claims()
    if tenant_id is None:
        return jsonify({'error': 'Missing or invalid tenant in token.'}), 400

    data = _normalize_vet_visit_payload(tenant_id, request.get_json() or {})
    if data.get('_cow_lookup_failed'):
        return jsonify({'error': 'Cow not found in tenant registry. Use cow_id or a valid cow tag.'}), 404

    return VetVisitService.update_visit(tenant_id, visit_id, data)


@safety_bp.route('/api/safety/dashboard', methods=['GET'])
@jwt_required()
@role_required(Role.FARMER, Role.VET, Role.FARM_HAND)
def safety_dashboard():
    tenant_id = _get_tenant_id_from_claims()
    if tenant_id is None:
        return jsonify({'error': 'Missing or invalid tenant in token.'}), 400

    page, per_page = _pagination_params()
    severity = (request.args.get('severity') or '').strip().lower()
    query = Cow.query.filter(Cow.is_hardlocked.is_(True), Cow.tenant_id == tenant_id)
    search = (request.args.get('q') or '').strip()
    if search:
        search_like = f"%{search}%"
        query = query.filter((Cow.name.ilike(search_like)) | (Cow.tag_number.ilike(search_like)))
    query = query.order_by(Cow.id.desc())
    paginated = query.paginate(page=page, per_page=per_page, error_out=False)

    items = []
    for cow in paginated.items:
        latest_medical = MedicalRecord.query.filter_by(cow_id=cow.id, tenant_id=tenant_id).order_by(MedicalRecord.visit_date.desc(), MedicalRecord.id.desc()).first()
        if latest_medical and latest_medical.withdrawal_days_recommended and latest_medical.withdrawal_days_recommended >= 14:
            computed_severity = 'high'
        elif latest_medical and latest_medical.withdrawal_days_recommended and latest_medical.withdrawal_days_recommended >= 7:
            computed_severity = 'medium'
        else:
            computed_severity = 'low'
        if severity and computed_severity != severity:
            continue

        lock_expires = None
        if latest_medical and latest_medical.visit_date and latest_medical.withdrawal_days_recommended:
            from datetime import timedelta
            lock_expires_dt = latest_medical.visit_date + timedelta(days=int(latest_medical.withdrawal_days_recommended))
            lock_expires = lock_expires_dt.isoformat()

        items.append({
            'cow_id': cow.id,
            'cow_name': cow.name,
            'cow_tag': cow.tag_number,
            'severity': computed_severity,
            'reason': latest_medical.diagnosis if latest_medical else 'Hardlock active',
            'lock_expires': lock_expires,
            'section': 'clinical',
            'medication': latest_medical.medication if latest_medical else None,
            'updated_at': latest_medical.visit_date.isoformat() if latest_medical and latest_medical.visit_date else None,
            'updated_by': latest_medical.vet_id if latest_medical else None,
            'notes': latest_medical.remarks if latest_medical else None,
        })

    return jsonify({
        'items': items,
        'meta': {
            'page': paginated.page,
            'per_page': paginated.per_page,
            'total': paginated.total,
            'pages': paginated.pages,
        },
    }), 200


@veterinary_bp.route('/api/veterinary/hardlocks/active', methods=['GET'])
@jwt_required()
@role_required(Role.FARMER, Role.VET, Role.FARM_HAND)
def list_active_hardlocks_alias():
    return safety_dashboard()