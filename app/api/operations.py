from __future__ import annotations
from flask import Blueprint, request, jsonify, g, current_app
from flask_jwt_extended import jwt_required, get_jwt_identity, get_jwt
from app.services.livestock_service import LivestockService
from app.services.production_service import ProductionService
from app.services.breeding_service import BreedingService
from app.repositories.cow_repo import CowRepository
from app.models.supply import MilkLog
from app.models.supply import MilkDropAlert
from app import db
from sqlalchemy import func
from datetime import date, datetime, timezone, timedelta
from app.utils.decorators import role_required
from app.utils.jwt_payload import parse_public_int_id
from app.models.user import Role
from app.models.livestock import AnimalTimelineEvent, LactationCycle

operations_bp = Blueprint('operations', __name__)
operations_alias_bp = Blueprint('operations_alias', __name__)


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


def _paginate_query(query):
    page, per_page = _pagination_params()
    paginated = query.paginate(page=page, per_page=per_page, error_out=False)
    return paginated


def _age_months(dob):
    if not dob:
        return None
    today = date.today()
    return max((today.year - dob.year) * 12 + (today.month - dob.month), 0)


def _get_tenant_id_from_claims():
    scope = _get_request_scope()
    return scope['tenant_id']


def _resolve_cow_by_identifier(animal_identifier, tenant_id):
    if animal_identifier is None:
        return None

    try:
        cow_id = int(animal_identifier)
    except (TypeError, ValueError):
        cow_id = None

    if cow_id is not None:
        cow = CowRepository.get_by_id(cow_id, tenant_id=tenant_id)
        if cow:
            return cow

    return CowRepository.get_by_tag(str(animal_identifier), tenant_id=tenant_id)


def _parse_public_or_int(value, prefix):
    if value is None:
        return None
    try:
        return parse_public_int_id(value, prefix)
    except (TypeError, ValueError, AttributeError):
        try:
            return int(value)
        except (TypeError, ValueError):
            return None


def _get_request_scope():
    claims = get_jwt() or {}
    tenant_raw = getattr(g, 'tenant_id', None) or claims.get('tenant_id')
    farm_raw = getattr(g, 'farm_id', None) or claims.get('farm_id')
    return {
        'tenant_id': _parse_public_or_int(tenant_raw, 'tenant_'),
        'farm_id': _parse_public_or_int(farm_raw, 'farm_'),
    }


def _milk_log_status(log):
    status = getattr(log, 'status', None)
    if status:
        return str(status).upper()
    if getattr(log, 'verified_at', None) is not None:
        return MilkLog.STATUS_VERIFIED
    if log.anomaly_flag:
        return MilkLog.STATUS_FLAGGED
    if not log.is_saleable:
        return MilkLog.STATUS_ISOLATED
    return MilkLog.STATUS_RECORDED


def _user_can_verify_yield():
    claims = get_jwt() or {}
    role = (claims.get('role') or '').strip().upper()
    return role in {Role.FARM_ADMIN, Role.FARM_MANAGER, Role.ADMIN, Role.SUPER_ADMIN}


def _serialize_milk_session(log):
    milking_date = log.timestamp.date().isoformat() if log.timestamp else None
    return {
        'id': log.id,
        'log_id': log.id,
        'cow_id': log.cow_id,
        'amount': float(log.amount_liters),
        'session': log.session,
        'milkingDate': milking_date,
        'status': _milk_log_status(log),
        'milker': log.recorded_by,
        'recorded_by': log.recorded_by,
        'timestamp': log.timestamp.isoformat() if log.timestamp else None,
        'is_saleable': log.is_saleable,
        'anomaly_detected': log.anomaly_flag,
        'verified_by': log.verified_by,
        'verified_at': log.verified_at.isoformat() if log.verified_at else None,
    }


def _serialize_animal_summary(cow):
    return {
        'id': cow.id,
        'tag_number': cow.tag_number,
        'name': cow.name,
        'breed': cow.breed_status,
        'breed_status': cow.breed_status,
        'date_of_birth': cow.date_of_birth.isoformat() if cow.date_of_birth else None,
        'current_status': cow.current_status,
        'is_active': cow.is_active,
    }


def _serialize_animal_event(event):
    return {
        'id': event.id,
        'cow_id': event.cow_id,
        'tenant_id': event.tenant_id,
        'event_type': event.event_type,
        'title': event.title,
        'description': event.description,
        'event_date': event.event_date.isoformat() if event.event_date else None,
        'event_data': event.event_data or {},
        'created_by': event.created_by,
        'created_at': event.created_at.isoformat() if event.created_at else None,
    }

@operations_bp.route('/cows/<int:cow_id>/milk', methods=['POST'])
@operations_bp.route('/livestock/<int:cow_id>/milk', methods=['POST'])
@jwt_required()
@role_required(Role.FARM_HAND, Role.FARMER) # Only Farm Hands and Farmer log the daily yield
def log_milk(cow_id):
    user_id = get_jwt_identity()
    tenant_id = _get_tenant_id_from_claims()
    if tenant_id is None:
        return jsonify({"error": "Missing or invalid tenant in token."}), 400

    data = request.get_json()
    
    amount = data.get('amount')
    session = data.get('session') # e.g., 'Morning' or 'Evening'
    
    if not amount or not session:
        return jsonify({"error": "Amount and Session parameters are required."}), 400
        
    try:
        amount_float = float(amount)
        if amount_float <= 0:
             return jsonify({"error": "Amount must be greater than 0."}), 400
    except ValueError:
        return jsonify({"error": "Amount must be a valid number."}), 400

    return ProductionService.log_daily_yield(cow_id, amount_float, session, user_id, tenant_id)


@operations_bp.route('/semen-inventory', methods=['POST'])
@jwt_required()
@role_required(Role.FARMER, Role.VET)
def add_semen_inventory():
    tenant_id = _get_tenant_id_from_claims()
    if tenant_id is None:
        return jsonify({"error": "Missing or invalid tenant in token."}), 400

    data = request.get_json() or {}
    return BreedingService.add_semen_inventory(tenant_id, data)


@operations_bp.route('/semen-inventory', methods=['GET'])
@jwt_required()
@role_required(Role.FARMER, Role.VET, Role.FARM_HAND)
def list_semen_inventory():
    tenant_id = _get_tenant_id_from_claims()
    if tenant_id is None:
        return jsonify({"error": "Missing or invalid tenant in token."}), 400

    return BreedingService.list_semen_inventory(tenant_id)


@operations_bp.route('/breeding-logs', methods=['POST'])
@jwt_required()
@role_required(Role.FARMER, Role.VET)
def log_insemination():
    tenant_id = _get_tenant_id_from_claims()
    if tenant_id is None:
        return jsonify({"error": "Missing or invalid tenant in token."}), 400

    data = request.get_json() or {}
    return BreedingService.log_insemination(tenant_id, data)


@operations_bp.route('/breeding-logs/<int:log_id>/status', methods=['PUT'])
@jwt_required()
@role_required(Role.FARMER, Role.VET)
def update_insemination_status(log_id):
    tenant_id = _get_tenant_id_from_claims()
    if tenant_id is None:
        return jsonify({"error": "Missing or invalid tenant in token."}), 400

    data = request.get_json() or {}
    return BreedingService.update_breeding_status(tenant_id, log_id, data)


@operations_bp.route('/breeding/performance', methods=['GET'])
@jwt_required()
@role_required(Role.FARMER, Role.VET)
def get_bull_performance_summary():
    tenant_id = _get_tenant_id_from_claims()
    if tenant_id is None:
        return jsonify({"error": "Missing or invalid tenant in token."}), 400

    return BreedingService.bull_performance_summary(tenant_id)


@operations_bp.route('/api/herd', methods=['GET'])
@jwt_required()
@role_required(Role.FARMER, Role.FARM_HAND, Role.VET)
def list_herd():
    tenant_id = _get_tenant_id_from_claims()
    if tenant_id is None:
        return jsonify({'error': 'Missing or invalid tenant in token.'}), 400
    status = request.args.get('status')
    search = (request.args.get('q') or '').strip()

    from app.models.livestock import Cow
    cows_query = Cow.query.filter(Cow.tenant_id == tenant_id)
    if status:
        cows_query = cows_query.filter(Cow.current_status == status)
    if search:
        search_like = f"%{search}%"
        cows_query = cows_query.filter((Cow.name.ilike(search_like)) | (Cow.tag_number.ilike(search_like)))
    cows_query = cows_query.order_by(Cow.id.desc())
    paginated = _paginate_query(cows_query)

    rows = [
        {
            'id': cow.id,
            'name': cow.name,
            'tag': cow.tag_number,
            'tag_number': cow.tag_number,
            'breed': cow.breed_status,
            'breed_status': cow.breed_status,
            'ageMonths': _age_months(cow.date_of_birth),
            'date_of_birth': cow.date_of_birth.isoformat(),
            'dob': cow.date_of_birth.isoformat(),
            'current_status': cow.current_status,
            'status': cow.current_status,
            'lastCalved': None,
            'milk': None,
            'createdAt': cow.created_at.isoformat() if cow.created_at else None,
            'updatedAt': cow.updated_at.isoformat() if cow.updated_at else None,
            'updatedBy': None,
            'is_hardlocked': cow.is_hardlocked,
            'is_active': cow.is_active,
        }
        for cow in paginated.items
    ]

    summary_query = Cow.query.filter(Cow.tenant_id == tenant_id)
    if status:
        summary_query = summary_query.filter(Cow.current_status == status)
    if search:
        search_like = f"%{search}%"
        summary_query = summary_query.filter((Cow.name.ilike(search_like)) | (Cow.tag_number.ilike(search_like)))

    summary_cows = summary_query.all()
    total_count = len(summary_cows)
    milking_count = sum(1 for cow in summary_cows if (cow.current_status or '').lower() == 'lactating')
    dry_count = sum(1 for cow in summary_cows if (cow.current_status or '').lower() == 'dry')
    age_months = [_age_months(cow.date_of_birth) for cow in summary_cows if cow.date_of_birth]
    average_age_months = (sum(age_months) / len(age_months)) if age_months else 0.0

    latest_calved_date = (
        db.session.query(func.max(LactationCycle.actual_calving_date))
        .join(Cow, LactationCycle.cow_id == Cow.id)
        .filter(Cow.tenant_id == tenant_id)
        .scalar()
    )

    summary = {
        'total_count': total_count,
        'milking_count': milking_count,
        'dry_count': dry_count,
        'average_age_months': average_age_months,
        'latest_calved': latest_calved_date.isoformat() if latest_calved_date else None,
    }

    return jsonify({'items': rows, 'meta': {'page': paginated.page, 'per_page': paginated.per_page, 'total': paginated.total, 'pages': paginated.pages}, 'summary': summary}), 200


@operations_bp.route('/api/herd', methods=['POST'])
@jwt_required()
@role_required(Role.FARMER)
def create_herd_member():
    tenant_id = _get_tenant_id_from_claims()
    if tenant_id is None:
        return jsonify({'error': 'Missing or invalid tenant in token.'}), 400

    data = request.get_json() or {}
    tag_number = (
        data.get('tag_number')
        or data.get('tag')
        or data.get('tagNumber')
        or data.get('id')
        or ''
    ).strip()
    date_of_birth = (
        data.get('date_of_birth')
        or data.get('dob')
        or data.get('dateOfBirth')
    )
    if not tag_number or not date_of_birth:
        return jsonify({'error': 'tag_number and date_of_birth are required.'}), 400
    from datetime import date
    try:
        dob = date.fromisoformat(str(date_of_birth))
    except ValueError:
        return jsonify({'error': 'date_of_birth must be in YYYY-MM-DD format.'}), 400
    existing_cow = CowRepository.get_by_tag(tag_number, tenant_id=tenant_id)
    if existing_cow:
        return jsonify({'error': 'Cow tag_number already exists for this tenant.'}), 409

    try:
        cow = CowRepository.create_livestock(
            tag_number=tag_number,
            date_of_birth=dob,
            name=data.get('name'),
            breed_status=data.get('breed_status') or 'Foundation',
            tenant_id=tenant_id,
        )
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 409
    return jsonify({
        'id': cow.id,
        'tag': cow.tag_number,
        'tag_number': cow.tag_number,
        'name': cow.name,
        'dob': cow.date_of_birth.isoformat(),
        'date_of_birth': cow.date_of_birth.isoformat(),
        'current_status': cow.current_status,
    }), 201


@operations_bp.route('/api/herd/<int:cow_id>', methods=['GET'])
@operations_bp.route('/api/animals/<int:cow_id>', methods=['GET'])
@operations_bp.route('/api/animals/<string:animal_id>', methods=['GET'])
@jwt_required()
@role_required(Role.FARMER, Role.FARM_HAND, Role.VET)
def get_herd_member(cow_id=None, animal_id=None):
    tenant_id = _get_tenant_id_from_claims()
    if tenant_id is None:
        return jsonify({'error': 'Missing or invalid tenant in token.'}), 400
    identifier = cow_id if cow_id is not None else animal_id
    cow = _resolve_cow_by_identifier(identifier, tenant_id)
    if not cow:
        return jsonify({'error': 'Animal not found.'}), 404
    payload = {
        'id': cow.id,
        'tag_number': cow.tag_number,
        'tag': cow.tag_number,
        'name': cow.name,
        'breed': cow.breed_status,
        'breed_status': cow.breed_status,
        'date_of_birth': cow.date_of_birth.isoformat(),
        'dob': cow.date_of_birth.isoformat(),
        'ageMonths': _age_months(cow.date_of_birth),
        'dam_id': cow.dam_id,
        'sire_name': cow.sire_name,
        'genetic_score': cow.genetic_score,
        'current_status': cow.current_status,
        'status': cow.current_status,
        'is_hardlocked': cow.is_hardlocked,
        'is_active': cow.is_active,
    }
    return jsonify(payload), 200


@operations_bp.route('/api/herd/<int:cow_id>', methods=['PATCH'])
@operations_bp.route('/api/animals/<int:cow_id>', methods=['PATCH'])
@operations_bp.route('/api/animals/<string:animal_id>', methods=['PATCH'])
@jwt_required()
@role_required(Role.FARMER)
def update_herd_member(cow_id=None, animal_id=None):
    tenant_id = _get_tenant_id_from_claims()
    if tenant_id is None:
        return jsonify({'error': 'Missing or invalid tenant in token.'}), 400
    identifier = cow_id if cow_id is not None else animal_id
    cow = _resolve_cow_by_identifier(identifier, tenant_id)
    if not cow:
        return jsonify({'error': 'Animal not found.'}), 404
    data = request.get_json() or {}
    if 'name' in data:
        cow.name = (data.get('name') or '').strip() or cow.name
    if 'breed_status' in data:
        cow.breed_status = data.get('breed_status')
    if 'current_status' in data:
        cow.current_status = data.get('current_status')
    if 'is_active' in data:
        cow.is_active = bool(data.get('is_active'))
    if 'is_hardlocked' in data:
        cow.is_hardlocked = bool(data.get('is_hardlocked'))
    db.session.commit()
    return jsonify({'id': cow.id, 'tag_number': cow.tag_number, 'name': cow.name, 'breed_status': cow.breed_status, 'current_status': cow.current_status, 'is_active': cow.is_active, 'updatedAt': cow.updated_at.isoformat() if cow.updated_at else None, 'updatedBy': get_jwt_identity()}), 200


@operations_bp.route('/api/herd/<int:cow_id>', methods=['DELETE'])
@jwt_required()
@role_required(Role.FARMER)
def delete_herd_member(cow_id):
    tenant_id = _get_tenant_id_from_claims()
    if tenant_id is None:
        return jsonify({'error': 'Missing or invalid tenant in token.'}), 400
    cow = CowRepository.get_by_id(cow_id, tenant_id=tenant_id)
    if not cow:
        return jsonify({'error': 'Animal not found.'}), 404
    db.session.delete(cow)
    db.session.commit()
    return jsonify({'message': 'Animal deleted successfully.', 'id': cow_id}), 200


@operations_bp.route('/api/animals/<int:cow_id>/milk-history', methods=['GET'])
@jwt_required()
@role_required(Role.FARMER, Role.FARM_HAND, Role.VET)
def animal_milk_history(cow_id):
    tenant_id = _get_tenant_id_from_claims()
    if tenant_id is None:
        return jsonify({'error': 'Missing or invalid tenant in token.'}), 400
    cow = CowRepository.get_by_id(cow_id, tenant_id=tenant_id)
    if not cow:
        return jsonify({'error': 'Animal not found.'}), 404

    query = MilkLog.query.filter_by(cow_id=cow_id, tenant_id=tenant_id)
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    if start_date:
        try:
            start_dt = datetime.fromisoformat(str(start_date))
            query = query.filter(MilkLog.timestamp >= start_dt)
        except ValueError:
            return jsonify({'error': 'start_date must be ISO format.'}), 400
    if end_date:
        try:
            end_dt = datetime.fromisoformat(str(end_date))
            query = query.filter(MilkLog.timestamp <= end_dt)
        except ValueError:
            return jsonify({'error': 'end_date must be ISO format.'}), 400
    summary_row = query.with_entities(
        func.count(MilkLog.id),
        func.coalesce(func.sum(MilkLog.amount_liters), 0),
        func.coalesce(func.avg(MilkLog.amount_liters), 0),
        func.coalesce(func.max(MilkLog.amount_liters), 0),
    ).first()

    session_count = int((summary_row[0] if summary_row else 0) or 0)
    total_logged = float((summary_row[1] if summary_row else 0) or 0)
    average_yield = float((summary_row[2] if summary_row else 0) or 0)
    peak_yield = float((summary_row[3] if summary_row else 0) or 0)

    query = query.order_by(MilkLog.timestamp.desc())
    paginated = _paginate_query(query)

    sessions = [_serialize_milk_session(log) for log in paginated.items]
    return jsonify({
        'animal': _serialize_animal_summary(cow),
        'summary': {
            'session_count': session_count,
            'total_logged': total_logged,
            'average_yield': average_yield,
            'peak_yield': peak_yield,
            # Aliases for frontend compatibility with different field names.
            'average': average_yield,
            'peak': peak_yield,
            'total': total_logged,
        },
        # Top-level aliases kept for clients that do not read nested summary.
        'session_count': session_count,
        'total_logged': total_logged,
        'average_yield': average_yield,
        'peak_yield': peak_yield,
        'average': average_yield,
        'peak': peak_yield,
        'sessions': sessions,
        'items': sessions,
        'meta': {
            'page': paginated.page,
            'per_page': paginated.per_page,
            'total': paginated.total,
            'pages': paginated.pages,
        },
    }), 200


@operations_bp.route('/api/animals/<string:animal_id>/events', methods=['GET', 'POST'])
@operations_alias_bp.route('/api/animals/<string:animal_id>/events', methods=['GET', 'POST'])
@jwt_required()
@role_required(Role.FARMER, Role.FARM_HAND, Role.VET)
def animal_events(animal_id):
    tenant_id = _get_tenant_id_from_claims()
    if tenant_id is None:
        return jsonify({'error': 'Missing or invalid tenant in token.'}), 400
    cow = _resolve_cow_by_identifier(animal_id, tenant_id)
    if not cow:
        return jsonify({'error': 'Animal not found.'}), 404

    if request.method == 'GET':
        query = AnimalTimelineEvent.query.filter_by(tenant_id=tenant_id, cow_id=cow.id).order_by(
            AnimalTimelineEvent.event_date.desc(),
            AnimalTimelineEvent.id.desc(),
        )
        paginated = _paginate_query(query)
        rows = [_serialize_animal_event(event) for event in paginated.items]
        return jsonify({'items': rows, 'meta': {'page': paginated.page, 'per_page': paginated.per_page, 'total': paginated.total, 'pages': paginated.pages}}), 200

    data = request.get_json(silent=True) or {}
    event_type = (data.get('event_type') or data.get('type') or '').strip()
    title = (data.get('title') or '').strip()
    description = (data.get('description') or data.get('notes') or '').strip() or None
    event_date_raw = data.get('event_date') or data.get('date') or data.get('timestamp')
    event_data = data.get('event_data') or data.get('metadata') or data.get('data') or {}

    if not event_type:
        event_type = 'general'
    if not title:
        title = event_type.replace('_', ' ').strip().title() or 'General Update'

    event_date = datetime.now(timezone.utc)
    if event_date_raw:
        try:
            event_date = datetime.fromisoformat(str(event_date_raw))
            if event_date.tzinfo is None:
                event_date = event_date.replace(tzinfo=timezone.utc)
        except ValueError:
            return jsonify({'error': 'event_date must be ISO format.'}), 400

    created_by = get_jwt_identity()
    try:
        created_by = int(created_by) if created_by is not None else None
    except (TypeError, ValueError):
        created_by = None

    event = AnimalTimelineEvent(
        tenant_id=tenant_id,
        cow_id=cow.id,
        event_type=event_type,
        title=title,
        description=description,
        event_date=event_date,
        event_data=event_data,
        created_by=created_by,
    )
    db.session.add(event)
    db.session.commit()

    return jsonify(_serialize_animal_event(event)), 201


@operations_bp.route('/api/production/yield', methods=['GET'])
@operations_bp.route('/api/production/yield', methods=['POST'])
@operations_bp.route('/api/production/yield/<int:log_id>', methods=['GET'])
@operations_bp.route('/api/production/yield/<int:log_id>', methods=['PATCH'])
@operations_bp.route('/api/production/yield/<int:log_id>', methods=['DELETE'])
@jwt_required()
@role_required(Role.FARMER, Role.FARM_HAND)
def production_yield_legacy(log_id=None):
    tenant_id = _get_tenant_id_from_claims()
    if tenant_id is None:
        return jsonify({'error': 'Missing or invalid tenant in token.'}), 400

    if request.method == 'GET' and log_id is None:
        query = MilkLog.query.filter_by(tenant_id=tenant_id)
        status_filter = request.args.get('status')
        if status_filter == 'anomaly':
            query = query.filter(MilkLog.anomaly_flag.is_(True))

        all_rows = query.all()
        status_counts = {
            'recorded': 0,
            'isolated': 0,
            'flagged': 0,
        }
        total_volume = 0.0
        for row in all_rows:
            total_volume += float(row.amount_liters or 0)
            status = _milk_log_status(row)
            if status == 'FLAGGED':
                status_counts['flagged'] += 1
            elif status == 'ISOLATED':
                status_counts['isolated'] += 1
            else:
                status_counts['recorded'] += 1

        summary = {
            'total_records': len(all_rows),
            'recorded_count': status_counts['recorded'],
            'isolated_count': status_counts['isolated'],
            'flagged_count': status_counts['flagged'],
            'total_volume': total_volume,
            # Frontend compatibility aliases.
            'verified_count': status_counts['recorded'],
            'pending_count': status_counts['isolated'],
            'totalVolume': total_volume,
            'verifiedEntries': status_counts['recorded'],
            'pendingEntries': status_counts['isolated'],
            'flaggedEntries': status_counts['flagged'],
        }

        query = query.order_by(MilkLog.timestamp.desc())
        paginated = _paginate_query(query)
        rows = [
            _serialize_milk_session(log)
            for log in paginated.items
        ]
        return jsonify({'items': rows, 'meta': {'page': paginated.page, 'per_page': paginated.per_page, 'total': paginated.total, 'pages': paginated.pages}, 'summary': summary}), 200
    if request.method == 'POST' and log_id is None:
        data = request.get_json() or {}
        cow_id = data.get('cow_id')
        amount = data.get('amount')
        session = data.get('session')
        if not cow_id or amount is None or not session:
            return jsonify({'error': 'cow_id, amount, and session are required.'}), 400
        user_id = get_jwt_identity()
        try:
            amount_float = float(amount)
            if amount_float <= 0:
                return jsonify({'error': 'Amount must be greater than 0.'}), 400
        except ValueError:
            return jsonify({'error': 'Amount must be a valid number.'}), 400
        return ProductionService.log_daily_yield(int(cow_id), amount_float, session, user_id, tenant_id)
    if request.method == 'GET':
        log = db.session.query(MilkLog).filter_by(id=log_id, tenant_id=tenant_id).first()
        if not log:
            return jsonify({'error': 'Production record not found.'}), 404
        cow = CowRepository.get_by_id(log.cow_id, tenant_id=tenant_id)
        cow_sessions_query = (
            MilkLog.query
            .filter_by(tenant_id=tenant_id, cow_id=log.cow_id)
            .order_by(MilkLog.timestamp.desc(), MilkLog.id.desc())
        )
        cow_sessions = cow_sessions_query.all()
        session_amounts = [float(session.amount_liters) for session in cow_sessions]
        average = (sum(session_amounts) / len(session_amounts)) if session_amounts else 0.0
        peak = max(session_amounts) if session_amounts else 0.0

        return jsonify({
            'id': log.id,
            'cow_id': log.cow_id,
            'cow_name': cow.name if cow else None,
            'breed': cow.breed_status if cow else None,
            'amount': float(log.amount_liters),
            'session': log.session,
            'milkingDate': log.timestamp.date().isoformat() if log.timestamp else None,
            'status': _milk_log_status(log),
            'average': average,
            'peak': peak,
            'sessions': [_serialize_milk_session(session) for session in cow_sessions],
        }), 200
    if request.method == 'PATCH':
        log = db.session.query(MilkLog).filter_by(id=log_id, tenant_id=tenant_id).first()
        if not log:
            return jsonify({'error': 'Production record not found.'}), 404

        data = request.get_json() or {}
        if 'session' in data:
            session_value = (data.get('session') or '').strip()
            if not session_value:
                return jsonify({'error': 'session cannot be empty.'}), 400
            log.session = session_value

        if 'amount' in data or 'amount_liters' in data:
            amount_raw = data.get('amount', data.get('amount_liters'))
            try:
                amount_float = float(amount_raw)
            except (TypeError, ValueError):
                return jsonify({'error': 'Amount must be a valid number.'}), 400
            if amount_float <= 0:
                return jsonify({'error': 'Amount must be greater than 0.'}), 400
            log.amount_liters = amount_float

        if 'milkingDate' in data or 'date' in data or 'timestamp' in data:
            date_raw = data.get('milkingDate') or data.get('date') or data.get('timestamp')
            if date_raw:
                try:
                    parsed_dt = datetime.fromisoformat(str(date_raw))
                except ValueError:
                    return jsonify({'error': 'milkingDate must be ISO format.'}), 400
                if parsed_dt.tzinfo is None:
                    parsed_dt = parsed_dt.replace(tzinfo=timezone.utc)
                log.timestamp = parsed_dt

        db.session.commit()
        return jsonify(_serialize_milk_session(log)), 200
    if request.method == 'DELETE':
        log = db.session.query(MilkLog).filter_by(id=log_id, tenant_id=tenant_id).first()
        if not log:
            return jsonify({'error': 'Production record not found.'}), 404
        db.session.delete(log)
        db.session.commit()
        return jsonify({'message': 'Production record deleted successfully.'}), 200


@operations_bp.route('/api/production/yield/<int:log_id>/verify', methods=['PATCH'])
@jwt_required()
def verify_production_yield(log_id):
    tenant_id = _get_tenant_id_from_claims()
    if tenant_id is None:
        return jsonify({'error': 'Missing or invalid tenant in token.'}), 400

    if not _user_can_verify_yield():
        return jsonify({'error': 'Forbidden.'}), 403

    log = db.session.query(MilkLog).filter_by(id=log_id, tenant_id=tenant_id).first()
    if not log:
        return jsonify({'error': 'Production record not found.'}), 404

    if _milk_log_status(log) == MilkLog.STATUS_VERIFIED:
        return jsonify(_serialize_milk_session(log)), 200

    log.status = MilkLog.STATUS_VERIFIED
    log.verified_by = int(get_jwt_identity())
    log.verified_at = datetime.now(timezone.utc)
    db.session.commit()
    return jsonify(_serialize_milk_session(log)), 200


@operations_bp.route('/api/production/history/<int:cow_id>', methods=['GET'])
@jwt_required()
@role_required(Role.FARMER, Role.FARM_HAND, Role.VET)
def production_history_alias(cow_id):
    return animal_milk_history(cow_id)


@operations_bp.route('/api/production/summary', methods=['GET'])
@jwt_required()
@role_required(Role.FARMER, Role.FARM_HAND, Role.VET)
def production_summary_alias():
    tenant_id = _get_tenant_id_from_claims()
    if tenant_id is None:
        return jsonify({'error': 'Missing or invalid tenant in token.'}), 400

    today = datetime.now(timezone.utc).date()
    start_of_day = datetime.combine(today, datetime.min.time(), tzinfo=timezone.utc)
    next_day = start_of_day + timedelta(days=1)

    total_liters = db.session.query(func.coalesce(func.sum(MilkLog.amount_liters), 0)).filter(
        MilkLog.tenant_id == tenant_id,
        MilkLog.timestamp >= start_of_day,
        MilkLog.timestamp < next_day,
    ).scalar() or 0

    saleable_liters = db.session.query(func.coalesce(func.sum(MilkLog.amount_liters), 0)).filter(
        MilkLog.tenant_id == tenant_id,
        MilkLog.timestamp >= start_of_day,
        MilkLog.timestamp < next_day,
        MilkLog.is_saleable.is_(True),
    ).scalar() or 0

    cows_milked = db.session.query(func.count(func.distinct(MilkLog.cow_id))).filter(
        MilkLog.tenant_id == tenant_id,
        MilkLog.timestamp >= start_of_day,
        MilkLog.timestamp < next_day,
    ).scalar() or 0

    from app.models.supply import InventoryItem, InventoryTransaction
    feed_cost = db.session.query(func.coalesce(func.sum(InventoryTransaction.total_transaction_value), 0)).join(
        InventoryItem,
        InventoryTransaction.item_id == InventoryItem.id,
    ).filter(
        InventoryItem.tenant_id == tenant_id,
        InventoryTransaction.transaction_type == 'OUT',
        InventoryTransaction.transaction_date >= start_of_day,
        InventoryTransaction.transaction_date < next_day,
    ).scalar() or 0

    price = float(current_app.config.get('STANDARD_MILK_PRICE_KES', 55.0))
    revenue_total = int(float(saleable_liters) * price)
    avg_per_cow = float(total_liters) / int(cows_milked) if cows_milked else 0.0
    profit_per_liter = (revenue_total - int(feed_cost)) / float(saleable_liters) if float(saleable_liters) > 0 else 0.0

    anomaly_count = db.session.query(func.count(MilkLog.id)).filter(
        MilkLog.tenant_id == tenant_id,
        MilkLog.timestamp >= start_of_day,
        MilkLog.timestamp < next_day,
        MilkLog.anomaly_flag.is_(True),
    ).scalar() or 0

    payload = {
        'date': today.isoformat(),
        'production_total_liters': float(total_liters),
        'saleable_liters': float(saleable_liters),
        'revenue_total_kes': revenue_total,
        'feed_cost_total_kes': int(feed_cost),
        'net_margin_kes': revenue_total - int(feed_cost),
        'operational_alerts': int(anomaly_count),
        'cows_milked': int(cows_milked),
        'avg_per_cow': avg_per_cow,
        'profit_per_liter': profit_per_liter,
        # Backward-compatibility aliases
        'total_liters': float(total_liters),
        'total_milk_today': float(total_liters),
        'cowsMilked': int(cows_milked),
        'avgPerCow': avg_per_cow,
        'profitPerLiter': profit_per_liter,
        'anomaly_count': int(anomaly_count),
    }
    return jsonify(payload), 200


@operations_bp.route('/api/production/milk-drop-alerts', methods=['GET'])
@jwt_required()
@role_required(Role.FARMER, Role.FARM_HAND, Role.VET)
def list_milk_drop_alerts():
    tenant_id = _get_tenant_id_from_claims()
    if tenant_id is None:
        return jsonify({'error': 'Missing or invalid tenant in token.'}), 400
    query = MilkDropAlert.query.filter_by(tenant_id=tenant_id)
    status = request.args.get('status')
    if status:
        query = query.filter(MilkDropAlert.status == status.upper())
    query = query.order_by(MilkDropAlert.alert_date.desc(), MilkDropAlert.id.desc())
    paginated = _paginate_query(query)
    from app.models.livestock import Cow

    rows = [
        {
            'id': alert.id,
            'cow_id': alert.cow_id,
            'cow_tag': (CowRepository.get_by_id(alert.cow_id, tenant_id=tenant_id).tag_number if CowRepository.get_by_id(alert.cow_id, tenant_id=tenant_id) else None),
            'date': alert.alert_date.isoformat(),
            'date_time': alert.alert_date.isoformat(),
            'missing_milk': float(alert.missing_milk_liters),
            'status': alert.status,
            'reason': alert.reason,
            'primary_reason': alert.reason,
            'investigation_notes': alert.investigation_notes,
            'selected_reasons': alert.selected_reasons or [],
            'investigated_by': alert.investigated_by,
            'investigated_at': alert.investigated_at.isoformat() if alert.investigated_at else None,
        }
        for alert in paginated.items
    ]
    return jsonify({'items': rows, 'meta': {'page': paginated.page, 'per_page': paginated.per_page, 'total': paginated.total, 'pages': paginated.pages}}), 200


@operations_bp.route('/api/production/milk-drop-alerts/<int:alert_id>/investigate', methods=['POST'])
@jwt_required()
@role_required(Role.FARMER, Role.VET)
def investigate_milk_drop_alert(alert_id):
    tenant_id = _get_tenant_id_from_claims()
    if tenant_id is None:
        return jsonify({'error': 'Missing or invalid tenant in token.'}), 400
    alert = MilkDropAlert.query.filter_by(id=alert_id, tenant_id=tenant_id).first()
    if not alert:
        return jsonify({'error': 'Milk-drop alert not found.'}), 404
    data = request.get_json() or {}
    alert.status = (data.get('status') or 'INVESTIGATING').strip().upper()
    if alert.status not in {'OPEN', 'INVESTIGATING', 'RESOLVED'}:
        return jsonify({'error': 'status must be OPEN, INVESTIGATING, or RESOLVED.'}), 400
    alert.investigation_notes = data.get('notes')
    alert.selected_reasons = data.get('selected_reasons') or data.get('reasons') or []
    user_id = get_jwt_identity()
    try:
        alert.investigated_by = int(user_id) if user_id is not None else None
    except (TypeError, ValueError):
        alert.investigated_by = None
    alert.investigated_at = datetime.now(timezone.utc)
    db.session.commit()
    return jsonify({'id': alert.id, 'status': alert.status, 'investigation_notes': alert.investigation_notes, 'selected_reasons': alert.selected_reasons, 'investigated_at': alert.investigated_at.isoformat() if alert.investigated_at else None}), 200


@operations_bp.route('/api/breeding', methods=['GET'])
@jwt_required()
@role_required(Role.FARMER, Role.FARM_HAND, Role.VET)
def breeding_alias_list():
    tenant_id = _get_tenant_id_from_claims()
    if tenant_id is None:
        return jsonify({'error': 'Missing or invalid tenant in token.'}), 400
    from app.models.livestock import BreedingLog
    query = BreedingLog.query.filter_by(tenant_id=tenant_id)
    status = request.args.get('status')
    if status:
        query = query.filter(BreedingLog.status == status.title())
    query = query.order_by(BreedingLog.id.desc())
    paginated = _paginate_query(query)
    rows = [
        {
            'id': row.id,
            'cow_id': row.cow_id,
            'semen_id': row.inventory_semen_id,
            'inventory_semen_id': row.inventory_semen_id,
            'external_sire_code': row.external_sire_code,
            'provided_by': row.provided_by,
            'semen_source_label': 'Farm Inventory' if row.provided_by == 'FARM' else 'Vet Provided',
            'insemination_date': row.insemination_date.isoformat() if row.insemination_date else None,
            'expected_calving_date': row.expected_calving_date.isoformat() if row.expected_calving_date else None,
            'status': row.status,
        }
        for row in paginated.items
    ]
    return jsonify({'items': rows, 'meta': {'page': paginated.page, 'per_page': paginated.per_page, 'total': paginated.total, 'pages': paginated.pages}}), 200


@operations_bp.route('/api/breeding', methods=['POST'])
@jwt_required()
@role_required(Role.FARMER, Role.VET)
def breeding_alias_create():
    tenant_id = _get_tenant_id_from_claims()
    if tenant_id is None:
        return jsonify({'error': 'Missing or invalid tenant in token.'}), 400
    data = request.get_json() or {}
    return BreedingService.log_insemination(tenant_id, data)


@operations_bp.route('/api/breeding/<int:log_id>', methods=['PATCH'])
@jwt_required()
@role_required(Role.FARMER, Role.VET)
def breeding_alias_update(log_id):
    tenant_id = _get_tenant_id_from_claims()
    if tenant_id is None:
        return jsonify({'error': 'Missing or invalid tenant in token.'}), 400
    data = request.get_json() or {}
    return BreedingService.update_breeding_status(tenant_id, log_id, data)


@operations_bp.route('/api/lab/entries', methods=['GET'])
@operations_bp.route('/api/clerk/entries', methods=['GET'])
@jwt_required()
@role_required(Role.FARMER, Role.FARM_HAND, Role.VET)
def list_lab_or_clerk_entries():
    tenant_id = _get_tenant_id_from_claims()
    if tenant_id is None:
        return jsonify({'error': 'Missing or invalid tenant in token.'}), 400
    query = MilkLog.query.filter_by(tenant_id=tenant_id).order_by(MilkLog.timestamp.desc(), MilkLog.id.desc())
    paginated = _paginate_query(query)
    rows = [
        {
            'id': row.id,
            'cow_id': row.cow_id,
            'amount_liters': float(row.amount_liters),
            'session': row.session,
            'butterfat_pct': float(row.butterfat_pct) if row.butterfat_pct is not None else None,
            'timestamp': row.timestamp.isoformat() if row.timestamp else None,
            'recorded_by': row.recorded_by,
        }
        for row in paginated.items
    ]
    return jsonify({'items': rows, 'meta': {'page': paginated.page, 'per_page': paginated.per_page, 'total': paginated.total, 'pages': paginated.pages}}), 200


@operations_bp.route('/api/lab/entries', methods=['POST'])
@operations_bp.route('/api/clerk/entries', methods=['POST'])
@jwt_required()
@role_required(Role.FARMER, Role.FARM_HAND, Role.VET)
def create_lab_or_clerk_entry():
    data = request.get_json() or {}
    cow_id = data.get('cow_id')
    amount = data.get('amount')
    session = data.get('session')
    if not cow_id or amount is None or not session:
        return jsonify({'error': 'cow_id, amount, and session are required.'}), 400
    user_id = get_jwt_identity()
    tenant_id = _get_tenant_id_from_claims()
    try:
        amount_float = float(amount)
        if amount_float <= 0:
            return jsonify({'error': 'Amount must be greater than 0.'}), 400
    except ValueError:
        return jsonify({'error': 'Amount must be a valid number.'}), 400
    return ProductionService.log_daily_yield(int(cow_id), amount_float, session, user_id, tenant_id)


@operations_alias_bp.route('/api/herd', methods=['GET'])
def list_herd_alias():
    return list_herd()


@operations_alias_bp.route('/api/herd', methods=['POST'])
def create_herd_member_alias():
    return create_herd_member()


@operations_alias_bp.route('/api/herd/<int:cow_id>', methods=['GET'])
def get_herd_member_alias(cow_id):
    return get_herd_member(cow_id)


@operations_alias_bp.route('/api/animals/<int:cow_id>', methods=['GET'])
@operations_alias_bp.route('/api/animals/<string:animal_id>', methods=['GET'])
def get_animal_alias(cow_id=None, animal_id=None):
    return get_herd_member(cow_id=cow_id, animal_id=animal_id)


@operations_alias_bp.route('/api/herd/<int:cow_id>', methods=['PATCH'])
def update_herd_member_alias(cow_id):
    return update_herd_member(cow_id)


@operations_alias_bp.route('/api/animals/<int:cow_id>', methods=['PATCH'])
@operations_alias_bp.route('/api/animals/<string:animal_id>', methods=['PATCH'])
def update_animal_alias(cow_id=None, animal_id=None):
    return update_herd_member(cow_id=cow_id, animal_id=animal_id)


@operations_alias_bp.route('/api/herd/<int:cow_id>', methods=['DELETE'])
def delete_herd_member_alias(cow_id):
    return delete_herd_member(cow_id)


@operations_alias_bp.route('/api/animals/<int:cow_id>/milk-history', methods=['GET'])
def animal_milk_history_alias(cow_id):
    return animal_milk_history(cow_id)


@operations_alias_bp.route('/api/production/yield', methods=['GET', 'POST'])
@operations_alias_bp.route('/api/production/yield/<int:log_id>', methods=['GET', 'PATCH', 'DELETE'])
def production_yield_alias(log_id=None):
    return production_yield_legacy(log_id)


@operations_alias_bp.route('/api/production/yield/<int:log_id>/verify', methods=['PATCH'])
def verify_production_yield_alias(log_id):
    return verify_production_yield(log_id)


@operations_alias_bp.route('/api/production/history/<int:cow_id>', methods=['GET'])
def production_history_alias_route(cow_id):
    return production_history_alias(cow_id)


@operations_alias_bp.route('/api/production/summary', methods=['GET'])
def production_summary_alias_route():
    return production_summary_alias()


@operations_alias_bp.route('/api/production/milk-drop-alerts', methods=['GET'])
def list_milk_drop_alerts_alias():
    return list_milk_drop_alerts()


@operations_alias_bp.route('/api/production/milk-drop-alerts/<int:alert_id>/investigate', methods=['POST'])
def investigate_milk_drop_alert_alias(alert_id):
    return investigate_milk_drop_alert(alert_id)


@operations_alias_bp.route('/api/breeding', methods=['GET'])
def breeding_alias_list_alias():
    return breeding_alias_list()


@operations_alias_bp.route('/api/breeding', methods=['POST'])
def breeding_alias_create_alias():
    return breeding_alias_create()


@operations_alias_bp.route('/api/breeding/<int:log_id>', methods=['PATCH'])
def breeding_alias_update_alias(log_id):
    return breeding_alias_update(log_id)


@operations_alias_bp.route('/api/lab/entries', methods=['GET'])
def list_lab_entries_alias():
    return list_lab_or_clerk_entries()


@operations_alias_bp.route('/api/lab/entries', methods=['POST'])
def create_lab_entries_alias():
    return create_lab_or_clerk_entry()


@operations_alias_bp.route('/api/clerk/entries', methods=['GET'])
def list_clerk_entries_alias():
    return list_lab_or_clerk_entries()


@operations_alias_bp.route('/api/clerk/entries', methods=['POST'])
def create_clerk_entries_alias():
    return create_lab_or_clerk_entry()