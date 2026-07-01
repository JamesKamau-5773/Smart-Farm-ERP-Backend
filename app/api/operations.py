from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity, get_jwt
from app.services.production_service import ProductionService
from app.services.breeding_service import BreedingService
from app.repositories.cow_repo import CowRepository
from app.models.supply import MilkLog
from app.models.supply import MilkDropAlert
from app import db
from sqlalchemy import func
from datetime import date, datetime, timezone
from app.utils.decorators import role_required
from app.utils.jwt_payload import parse_public_int_id
from app.models.user import Role

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
    claims = get_jwt()
    tenant_public_id = claims.get('tenant_id')
    if not tenant_public_id:
        return None
    try:
        return parse_public_int_id(tenant_public_id, 'tenant_')
    except (TypeError, ValueError):
        return None

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
    status = request.args.get('status')
    search = (request.args.get('q') or '').strip()

    from app.models.livestock import Cow
    cows_query = Cow.query
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
            'createdAt': None,
            'updatedAt': None,
            'updatedBy': None,
            'is_hardlocked': cow.is_hardlocked,
            'is_active': cow.is_active,
        }
        for cow in paginated.items
    ]
    return jsonify({'items': rows, 'meta': {'page': paginated.page, 'per_page': paginated.per_page, 'total': paginated.total, 'pages': paginated.pages}}), 200


@operations_bp.route('/api/herd', methods=['POST'])
@jwt_required()
@role_required(Role.FARMER)
def create_herd_member():
    data = request.get_json() or {}
    tag_number = (data.get('tag_number') or '').strip()
    date_of_birth = data.get('date_of_birth')
    if not tag_number or not date_of_birth:
        return jsonify({'error': 'tag_number and date_of_birth are required.'}), 400
    from datetime import date
    try:
        dob = date.fromisoformat(str(date_of_birth))
    except ValueError:
        return jsonify({'error': 'date_of_birth must be in YYYY-MM-DD format.'}), 400
    cow = CowRepository.create_livestock(tag_number=tag_number, date_of_birth=dob, name=data.get('name'), breed_status=data.get('breed_status') or 'Foundation')
    return jsonify({'id': cow.id, 'tag_number': cow.tag_number, 'name': cow.name, 'current_status': cow.current_status}), 201


@operations_bp.route('/api/herd/<int:cow_id>', methods=['GET'])
@operations_bp.route('/api/animals/<int:cow_id>', methods=['GET'])
@jwt_required()
@role_required(Role.FARMER, Role.FARM_HAND, Role.VET)
def get_herd_member(cow_id):
    cow = CowRepository.get_by_id(cow_id)
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
@jwt_required()
@role_required(Role.FARMER)
def update_herd_member(cow_id):
    cow = CowRepository.get_by_id(cow_id)
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
    return jsonify({'id': cow.id, 'tag_number': cow.tag_number, 'name': cow.name, 'breed_status': cow.breed_status, 'current_status': cow.current_status, 'is_active': cow.is_active, 'updatedAt': datetime.now(timezone.utc).isoformat(), 'updatedBy': get_jwt_identity()}), 200


@operations_bp.route('/api/herd/<int:cow_id>', methods=['DELETE'])
@jwt_required()
@role_required(Role.FARMER)
def delete_herd_member(cow_id):
    from app.models.livestock import Cow
    cow = db.session.get(Cow, cow_id)
    if not cow:
        return jsonify({'error': 'Animal not found.'}), 404
    db.session.delete(cow)
    db.session.commit()
    return jsonify({'message': 'Animal deleted successfully.', 'id': cow_id}), 200


@operations_bp.route('/api/animals/<int:cow_id>/milk-history', methods=['GET'])
@jwt_required()
@role_required(Role.FARMER, Role.FARM_HAND, Role.VET)
def animal_milk_history(cow_id):
    query = MilkLog.query.filter_by(cow_id=cow_id)
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
    query = query.order_by(MilkLog.timestamp.desc())
    paginated = _paginate_query(query)

    rows = [
        {
            'id': log.id,
            'cow_id': log.cow_id,
            'date': log.timestamp.date().isoformat() if log.timestamp else None,
            'liters': float(log.amount_liters),
            'notes': f"Session: {log.session}",
            'amount_liters': float(log.amount_liters),
            'session': log.session,
            'timestamp': log.timestamp.isoformat() if log.timestamp else None,
            'recorded_by': log.recorded_by,
            'is_saleable': log.is_saleable,
            'anomaly_flag': log.anomaly_flag,
        }
        for log in paginated.items
    ]
    return jsonify({'items': rows, 'meta': {'page': paginated.page, 'per_page': paginated.per_page, 'total': paginated.total, 'pages': paginated.pages}}), 200


@operations_bp.route('/api/production/yield', methods=['GET'])
@operations_bp.route('/api/production/yield', methods=['POST'])
@operations_bp.route('/api/production/yield/<int:log_id>', methods=['GET'])
@operations_bp.route('/api/production/yield/<int:log_id>', methods=['DELETE'])
@jwt_required()
@role_required(Role.FARMER, Role.FARM_HAND)
def production_yield_legacy(log_id=None):
    if request.method == 'GET' and log_id is None:
        tenant_id = _get_tenant_id_from_claims()
        query = MilkLog.query.filter_by(tenant_id=tenant_id)
        status_filter = request.args.get('status')
        if status_filter == 'anomaly':
            query = query.filter(MilkLog.anomaly_flag.is_(True))
        query = query.order_by(MilkLog.timestamp.desc())
        paginated = _paginate_query(query)
        rows = [
            {
                'id': log.id,
                'cow_id': log.cow_id,
                'amount_liters': float(log.amount_liters),
                'session': log.session,
                'timestamp': log.timestamp.isoformat() if log.timestamp else None,
                'recorded_by': log.recorded_by,
                'is_saleable': log.is_saleable,
                'anomaly_flag': log.anomaly_flag,
            }
            for log in paginated.items
        ]
        return jsonify({'items': rows, 'meta': {'page': paginated.page, 'per_page': paginated.per_page, 'total': paginated.total, 'pages': paginated.pages}}), 200
    if request.method == 'POST' and log_id is None:
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
    if request.method == 'GET':
        log = db.session.get(MilkLog, log_id)
        if not log:
            return jsonify({'error': 'Production record not found.'}), 404
        return jsonify({'id': log.id, 'cow_id': log.cow_id, 'amount_liters': float(log.amount_liters), 'session': log.session, 'timestamp': log.timestamp.isoformat()}), 200
    if request.method == 'DELETE':
        log = db.session.get(MilkLog, log_id)
        if not log:
            return jsonify({'error': 'Production record not found.'}), 404
        db.session.delete(log)
        db.session.commit()
        return jsonify({'message': 'Production record deleted successfully.'}), 200


@operations_bp.route('/api/production/summary', methods=['GET'])
@jwt_required()
@role_required(Role.FARMER, Role.FARM_HAND, Role.VET)
def production_summary_alias():
    tenant_id = _get_tenant_id_from_claims()
    if tenant_id is None:
        return jsonify({'error': 'Missing or invalid tenant in token.'}), 400
    total_liters = db.session.query(func.coalesce(func.sum(MilkLog.amount_liters), 0)).filter(MilkLog.tenant_id == tenant_id).scalar() or 0
    anomaly_count = db.session.query(func.count(MilkLog.id)).filter(MilkLog.tenant_id == tenant_id, MilkLog.anomaly_flag.is_(True)).scalar() or 0
    return jsonify({'total_liters': float(total_liters), 'anomaly_count': int(anomaly_count)}), 200


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
            'cow_tag': (db.session.get(Cow, alert.cow_id).tag_number if db.session.get(Cow, alert.cow_id) else None),
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
            'semen_id': row.semen_id,
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
def get_animal_alias(cow_id):
    return get_herd_member(cow_id)


@operations_alias_bp.route('/api/herd/<int:cow_id>', methods=['PATCH'])
def update_herd_member_alias(cow_id):
    return update_herd_member(cow_id)


@operations_alias_bp.route('/api/animals/<int:cow_id>', methods=['PATCH'])
def update_animal_alias(cow_id):
    return update_herd_member(cow_id)


@operations_alias_bp.route('/api/herd/<int:cow_id>', methods=['DELETE'])
def delete_herd_member_alias(cow_id):
    return delete_herd_member(cow_id)


@operations_alias_bp.route('/api/animals/<int:cow_id>/milk-history', methods=['GET'])
def animal_milk_history_alias(cow_id):
    return animal_milk_history(cow_id)


@operations_alias_bp.route('/api/production/yield', methods=['GET', 'POST'])
@operations_alias_bp.route('/api/production/yield/<int:log_id>', methods=['GET', 'DELETE'])
def production_yield_alias(log_id=None):
    return production_yield_legacy(log_id)


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