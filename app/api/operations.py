from __future__ import annotations
from flask import Blueprint, request, jsonify, g, current_app, Response
from flask_jwt_extended import jwt_required, get_jwt_identity, get_jwt
from app.services.livestock_service import LivestockService
from app.services.production_service import ProductionService
from app.services.breeding_service import BreedingService
from app.services.finance_service import FinanceService
from app.services.genetic_projection_service import GeneticProjectionService
from app.repositories.cow_repo import CowRepository
from app.repositories.breeding_repo import BreedingLogRepository
from app.models.supply import MilkLog
from app.models.supply import MilkDropAlert
from app.models.finance import Transaction, TransactionCategory, TransactionType
from app import db
from sqlalchemy import func, case, exc
from sqlalchemy.orm import aliased
from sqlalchemy.exc import IntegrityError
from datetime import date, datetime, time as dt_time, timezone, timedelta
from decimal import Decimal
import time
from app.utils.decorators import role_required
from app.utils.jwt_payload import parse_public_int_id
from app.models.user import Role, User
from app.models.genetics import GeneticProfile, GeneticTraitDefinition, GeneticTraitScore
from app.models.livestock import AnimalTimelineEvent, LactationCycle, Cow
from app.services.cow_status_service import CowStatusService
from app.repositories.milk_disposition_repo import MilkInventoryRepository

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


def _serialize_dam_summary(dam_id, tenant_id):
    """Expands a bare dam_id into authoritative parent data so callers never guess labels from an ID."""
    if not dam_id:
        return None
    dam = CowRepository.get_by_id(dam_id, tenant_id=tenant_id)
    if not dam:
        return None
    return {'id': dam.id, 'tag_number': dam.tag_number, 'name': dam.name}


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
    # Flags are authoritative over the column's generic 'RECORDED' default; only an explicit
    # VERIFIED status (or verified_at) should short-circuit the flag-derived status below.
    status = getattr(log, 'status', None)
    if status and str(status).upper() == MilkLog.STATUS_VERIFIED:
        return MilkLog.STATUS_VERIFIED
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
    return role in {Role.FARM_ADMIN, Role.FARM_MANAGER, Role.ADMIN, Role.SUPER_ADMIN, Role.FARMER}


def _serialize_milk_session(log, cow_tag=None, cow_name=None, milker_name=None):
    milking_date = log.timestamp.date().isoformat() if log.timestamp else None
    return {
        'id': log.id,
        'log_id': log.id,
        'cow_id': log.cow_id,
        'amount': float(log.amount_liters),
        'session': log.session,
        'cow_tag': cow_tag,
        'cow_name': cow_name,
        'milkingDate': milking_date,
        'status': _milk_log_status(log),
        'milker': log.recorded_by,
        'milker_name': milker_name,
        'recorded_by': log.recorded_by,
        'timestamp': log.timestamp.isoformat() if log.timestamp else None,
        'is_saleable': log.is_saleable,
        'anomaly_detected': log.anomaly_flag,
        'verified_by': log.verified_by,
        'verified_at': log.verified_at.isoformat() if log.verified_at else None,
    }


def _parse_history_date_bounds(start_date_raw, end_date_raw):
    start_dt = None
    end_dt = None
    end_is_exclusive = False

    if start_date_raw:
        parsed = datetime.fromisoformat(str(start_date_raw))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        start_dt = parsed

    if end_date_raw:
        raw = str(end_date_raw)
        parsed = datetime.fromisoformat(raw)
        if parsed.tzinfo is None and len(raw) == 10:
            # Date-only end filters should include the whole day.
            end_dt = datetime.combine(parsed.date() + timedelta(days=1), dt_time.min, tzinfo=timezone.utc)
            end_is_exclusive = True
        else:
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            end_dt = parsed

    return start_dt, end_dt, end_is_exclusive


def _compute_daily_average_and_peak(log_rows):
    if not log_rows:
        return 0.0, 0.0

    daily_totals = {}
    for row in log_rows:
        if row.timestamp is None:
            continue
        day_key = row.timestamp.date().isoformat()
        daily_totals[day_key] = daily_totals.get(day_key, 0.0) + float(row.amount_liters or 0)

    if not daily_totals:
        return 0.0, 0.0

    totals = list(daily_totals.values())
    return (sum(totals) / len(totals)), max(totals)


def _compute_recent_cow_yield(cow_id, tenant_id, today=None):
    today = today or date.today()
    seven_day_start = today - timedelta(days=7)
    rows = (
        MilkLog.query.filter(
            MilkLog.tenant_id == tenant_id,
            MilkLog.cow_id == cow_id,
            MilkLog.timestamp >= datetime.combine(seven_day_start - timedelta(days=1), dt_time.min, tzinfo=timezone.utc),
            MilkLog.timestamp < datetime.combine(today + timedelta(days=1), dt_time.min, tzinfo=timezone.utc),
        )
        .all()
    )

    daily_totals = {}
    for row in rows:
        if row.timestamp is None:
            continue
        log_date = row.timestamp.date()
        daily_totals[log_date] = daily_totals.get(log_date, 0.0) + float(row.amount_liters or 0)

    yesterday = today - timedelta(days=1)
    seven_day_total = sum(daily_totals.get(today - timedelta(days=offset), 0.0) for offset in range(1, 8))
    return {
        'yesterday_yield_liters': round(daily_totals.get(yesterday, 0.0), 2),
        'seven_day_average_liters': round(seven_day_total / 7, 2),
    }

def _augment_yield_response(response_data, status_code, tenant_id):
    """
    Enrich a successful yield response with cow name and tag for the frontend.
    This function also acts as a workaround for service methods that incorrectly
    return a Flask Response object instead of a data dictionary.
    """
    # If the service layer returned a Response object, we need to extract its data.
    if isinstance(response_data, Response):
        # For non-success responses, just return the original response.
        if status_code >= 300:
            return response_data

        # For success responses, get the json data to augment it.
        try:
            data = response_data.get_json()
        except Exception:
            # If it's not a JSON response, we can't augment it.
            return response_data
    else:
        data = response_data

    # Only hit the database if the log was successful and we have a cow_id
    if status_code < 300 and isinstance(data, dict) and data.get('cow_id'):
        try:
            cow = CowRepository.get_by_id(data['cow_id'], tenant_id)
            if cow:
                data['cow_tag'] = cow.tag_number
                data['cow_name'] = cow.name
        except Exception:
            # If the DB lookup fails for any reason, fail gracefully.
            # We still want to return the successful milk log to the user.
            pass

    return jsonify(data), status_code

def _parse_milking_date(data):
    """Extract and validate an optional milking date (milking_date/milkingDate) from a request body.

    Returns a (date, error_response) tuple; error_response is None on success.
    """
    raw = data.get('milking_date') or data.get('milkingDate')
    if not raw:
        return None, None
    try:
        return datetime.strptime(raw, '%Y-%m-%d').date(), None
    except (ValueError, TypeError):
        return None, (jsonify({'error': 'milking_date must be in YYYY-MM-DD format.'}), 400)


def _serialize_animal_summary(cow, tenant_id=None):
    payload = {
        'id': cow.id,
        'tag_number': cow.tag_number,
        'tag': cow.tag_number,
        'name': cow.name,
        'breed': cow.breed_status,
        'breed_status': cow.breed_status,
        'date_of_birth': cow.date_of_birth.isoformat() if cow.date_of_birth else None,
        'dob': cow.date_of_birth.isoformat() if cow.date_of_birth else None,
        # Use the raw status here; it will be overwritten by compute_status_fields if tenant_id is provided.
        'status': cow.status,
        'current_status': cow.status,
        'last_calving_date': cow.last_calving_date.isoformat() if cow.last_calving_date else None,
        'last_calved': cow.last_calving_date.isoformat() if cow.last_calving_date else None,
        'pregnancy_status': cow.pregnancy_status,
        'due_date': cow.due_date.isoformat() if cow.due_date else None,
        'dam_id': cow.dam_id,
        'dam': _serialize_dam_summary(cow.dam_id, tenant_id) if tenant_id is not None else None,
        'sire_name': cow.sire_name,
        'birth_weight_kg': float(cow.birth_weight_kg) if cow.birth_weight_kg is not None else None,
        'photo_url': cow.photo_url,
        'is_active': cow.is_active,
    }
    if tenant_id is not None:
        payload.update(CowStatusService.compute_status_fields(cow, tenant_id))
        payload.update(_compute_recent_cow_yield(cow.id, tenant_id))
    return payload


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


@operations_bp.route('/cows/<int:cow_id_or_tag>/milk', methods=['POST'])
@operations_bp.route('/livestock/<string:cow_id_or_tag>/milk', methods=['POST'])
@jwt_required()
@role_required(Role.FARM_HAND, Role.FARMER) # Only Farm Hands and Farmer log the daily yield
def log_milk(cow_id_or_tag):
    user_id = get_jwt_identity() # This is the user ID, not the cow ID
    tenant_id = _get_tenant_id_from_claims()
    if tenant_id is None:
        return jsonify({"error": "Missing or invalid tenant in token."}), 400

    data = request.get_json()

    amount = data.get('amount')
    session = data.get('session') # e.g., 'Morning', 'Evening', or 'Midday'

    if not amount or not session:
        return jsonify({"error": "Amount and Session parameters are required."}), 400

    try:
        amount_float = float(amount)
        if amount_float <= 0:
             return jsonify({"error": "Amount must be greater than 0."}), 400
    except ValueError:
        return jsonify({"error": "Amount must be a valid number."}), 400

    milking_date, date_error = _parse_milking_date(data)
    if date_error:
        return date_error

    cow = _resolve_cow_by_identifier(cow_id_or_tag, tenant_id)
    if not cow:
        return jsonify({'error': 'Animal not found.'}), 404

    cow_id = cow.id # Use the resolved integer cow_id
    response_data, status_code = ProductionService.log_daily_yield(cow_id, amount_float, session, user_id, tenant_id, milking_date=milking_date)
    return _augment_yield_response(response_data, status_code, tenant_id)


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


@operations_bp.route('/breeding-logs', methods=['GET'])
@jwt_required()
@role_required(Role.FARMER, Role.FARM_HAND, Role.VET)
def list_insemination_logs():
    """Provides a GET endpoint for the legacy /breeding-logs path for listing."""
    # Delegates to the canonical implementation to avoid code duplication.
    return breeding_alias_list()


@operations_bp.route('/breeding-logs/<int:log_id>/certificate', methods=['POST'])
@jwt_required()
@role_required(Role.FARMER, Role.VET)
def upload_breeding_certificate(log_id):
    tenant_id = _get_tenant_id_from_claims()
    if tenant_id is None:
        return jsonify({"error": "Missing or invalid tenant in token."}), 400

    file_storage = request.files.get('file') or request.files.get('certificate')
    return BreedingService.attach_certificate_image(tenant_id, log_id, file_storage)


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
    # Allow clients to request inactive animals if needed for archival views.
    include_inactive = str(request.args.get('include_inactive', 'false')).lower() == 'true'

    from app.models.livestock import Cow
    cows_query = Cow.query.filter(Cow.tenant_id == tenant_id)

    if not include_inactive:
        cows_query = cows_query.filter(Cow.is_active.is_(True))

    if status:
        cows_query = cows_query.filter(Cow.current_status == status)
    if search:
        search_like = f"%{search}%"
        cows_query = cows_query.filter((Cow.name.ilike(search_like)) | (Cow.tag_number.ilike(search_like)))
    cows_query = cows_query.order_by(Cow.id.desc())
    paginated = _paginate_query(cows_query)

    rows = []
    for cow in paginated.items:
        computed_fields = CowStatusService.compute_status_fields(cow, tenant_id)
        row_data = {
            'id': cow.id,
            'name': cow.name,
            'tag': cow.tag_number,
            'tag_number': cow.tag_number,
            'breed': cow.breed_status,
            'breed_status': cow.breed_status,
            'ageMonths': _age_months(cow.date_of_birth),
            'date_of_birth': cow.date_of_birth.isoformat(),
            'dob': cow.date_of_birth.isoformat(),
            'lastCalved': None,
            'milk': None,
            'createdAt': cow.created_at.isoformat() if cow.created_at else None,
            'updatedAt': cow.updated_at.isoformat() if cow.updated_at else None,
            'updatedBy': None,
            'is_hardlocked': cow.is_hardlocked,
            'is_active': cow.is_active,
            **computed_fields,
        }
        row_data['status'] = row_data['current_status']
        rows.append(row_data)

    summary_query = Cow.query.filter(Cow.tenant_id == tenant_id)

    if not include_inactive:
        summary_query = summary_query.filter(Cow.is_active.is_(True))

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
    dam_id = data.get('dam_id') or data.get('damId')
    sire_pta_scores = data.get('sire_pta_scores') or data.get('sirePTAScores')

    if not tag_number or not date_of_birth:
        return jsonify({'error': 'tag_number and date_of_birth are required.'}), 400
    from datetime import date
    try:
        dob = date.fromisoformat(str(date_of_birth))
    except ValueError:
        return jsonify({'error': 'date_of_birth must be in YYYY-MM-DD format.'}), 400

    # Check for an ACTIVE cow with the same tag number.
    # The unique constraint is on active cows, but this provides a clearer error message.
    from app.models.livestock import Cow
    existing_cow = Cow.query.filter_by(
        tenant_id=tenant_id, tag_number=tag_number, is_active=True
    ).first()
    if existing_cow:
        return jsonify({'error': 'An active cow with this tag_number already exists for this tenant.'}), 409

    try:
        cow = CowRepository.create_livestock(
            tag_number=tag_number,
            date_of_birth=dob,
            name=data.get('name'),
            breed_status=data.get('breed_status') or 'Foundation',
            tenant_id=tenant_id,
            dam_id=dam_id,
        )
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 409

    # Wire genetic projection if dam_id is provided
    if dam_id and cow.id:
        try:
            # If sire_pta_scores not provided in request, fetch from most recent breeding log
            if not sire_pta_scores:
                breeding_log = BreedingLogRepository.get_most_recent_pregnant_for_cow(dam_id, tenant_id)
                if breeding_log and breeding_log.traits_to_improve:
                    # traits_to_improve is stored as JSON string from SemenInventory
                    import json
                    try:
                        sire_pta_scores = json.loads(breeding_log.traits_to_improve) if isinstance(breeding_log.traits_to_improve, str) else breeding_log.traits_to_improve
                    except (json.JSONDecodeError, TypeError):
                        sire_pta_scores = {}

            # Project calf genetic scores if sire PTA info exists
            if sire_pta_scores:
                GeneticProjectionService.project_calf_scores(
                    calf_cow_id=cow.id,
                    dam_cow_id=dam_id,
                    sire_pta_scores=sire_pta_scores,
                    tenant_id=tenant_id,
                )
                current_app.logger.info(f"Auto-projected genetic scores for calf {cow.id} from dam {dam_id}")
        except Exception as e:
            # Log the error but don't fail calf registration
            current_app.logger.warning(f"Failed to project genetic scores for calf {cow.id}: {str(e)}")

    return jsonify({
        'id': cow.id,
        'tag': cow.tag_number,
        'tag_number': cow.tag_number,
        'name': cow.name,
        'dob': cow.date_of_birth.isoformat(),
        'date_of_birth': cow.date_of_birth.isoformat(),
        'current_status': cow.current_status,
        'dam_id': cow.dam_id,
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
    computed_fields = CowStatusService.compute_status_fields(cow, tenant_id)
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
        'dam': _serialize_dam_summary(cow.dam_id, tenant_id),
        'sire_name': cow.sire_name,
        'birth_weight_kg': float(cow.birth_weight_kg) if cow.birth_weight_kg is not None else None,
        'photo_url': cow.photo_url,
        'last_calving_date': cow.last_calving_date.isoformat() if cow.last_calving_date else None,
        'last_calved': cow.last_calving_date.isoformat() if cow.last_calving_date else None,
        'genetic_score': cow.genetic_score,
        'is_hardlocked': cow.is_hardlocked,
        'is_active': cow.is_active,
        **computed_fields,
        **_compute_recent_cow_yield(cow.id, tenant_id),
    }
    payload['status'] = payload['current_status']
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
    tag_number = data.get('tag_number') or data.get('tag') or data.get('tagNumber')
    if tag_number is not None:
        tag_number = str(tag_number).strip()
        if not tag_number:
            return jsonify({'error': 'tag_number cannot be empty.'}), 400
        if tag_number != cow.tag_number:
            duplicate = Cow.query.filter_by(
                tenant_id=tenant_id, tag_number=tag_number, is_active=True
            ).filter(Cow.id != cow.id).first()
            if duplicate:
                return jsonify({'error': 'An active cow with this tag_number already exists for this tenant.'}), 409
        cow.tag_number = tag_number
    if 'name' in data:
        cow.name = data.get('name')
    if 'breed_status' in data or 'breed' in data:
        cow.breed_status = data.get('breed_status', data.get('breed'))
    date_of_birth_raw = data.get('date_of_birth') or data.get('dob') or data.get('dateOfBirth')
    if date_of_birth_raw:
        try:
            cow.date_of_birth = datetime.strptime(date_of_birth_raw, '%Y-%m-%d').date()
        except ValueError:
            return jsonify({'error': 'date_of_birth must be in YYYY-MM-DD format.'}), 400
    if 'current_status' in data:
        # FIX: Update the 'status' database column, not the 'current_status' property
        cow.status = data.get('current_status')
    if 'is_active' in data:
        cow.is_active = bool(data.get('is_active'))
    if 'is_hardlocked' in data:
        cow.is_hardlocked = bool(data.get('is_hardlocked'))

    # Add new fields for sire name, dam ID, and status-related dates
    if 'sire_name' in data:
        cow.sire_name = data.get('sire_name')
    if 'dam_id' in data:
        # Ensure dam_id is set to None if an empty string is passed (for optional foreign keys)
        cow.dam_id = data['dam_id'] if data['dam_id'] != '' else None
    birth_weight_raw = data.get('birth_weight_kg', data.get('birth_weight'))
    if birth_weight_raw is not None:
        if birth_weight_raw == '':
            cow.birth_weight_kg = None
        else:
            try:
                cow.birth_weight_kg = round(float(birth_weight_raw), 2)
            except (TypeError, ValueError):
                return jsonify({'error': 'birth_weight_kg must be a valid number.'}), 400

    if 'last_calving_date' in data and data['last_calving_date'] is not None:
        try:
            cow.last_calving_date = datetime.strptime(data['last_calving_date'], '%Y-%m-%d').date()
        except ValueError:
            return jsonify({'error': 'last_calving_date must be in YYYY-MM-DD format.'}), 400
    if 'pregnancy_status' in data:
        cow.pregnancy_status = data.get('pregnancy_status')
    if 'due_date' in data and data['due_date'] is not None:
        try:
            cow.due_date = datetime.strptime(data['due_date'], '%Y-%m-%d').date()
        except ValueError:
            return jsonify({'error': 'due_date must be in YYYY-MM-DD format.'}), 400

    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({'error': 'An active cow with this tag_number already exists for this tenant.'}), 409

    # Return a comprehensive payload consistent with GET /api/animals/<cow_id>
    computed_fields = CowStatusService.compute_status_fields(cow, tenant_id)
    payload = {
        'id': cow.id, 'tag_number': cow.tag_number, 'tag': cow.tag_number,
        'name': cow.name, 'breed': cow.breed_status, 'breed_status': cow.breed_status,
        'date_of_birth': cow.date_of_birth.isoformat() if cow.date_of_birth else None, 'dob': cow.date_of_birth.isoformat() if cow.date_of_birth else None,
        'ageMonths': _age_months(cow.date_of_birth), 'dam_id': cow.dam_id,
        'dam': _serialize_dam_summary(cow.dam_id, tenant_id), 'sire_name': cow.sire_name,
        'birth_weight_kg': float(cow.birth_weight_kg) if cow.birth_weight_kg is not None else None,
        'photo_url': cow.photo_url,
        'genetic_score': cow.genetic_score, 'is_hardlocked': cow.is_hardlocked, 'is_active': cow.is_active,
        'last_calving_date': cow.last_calving_date.isoformat() if cow.last_calving_date else None,
        'pregnancy_status': cow.pregnancy_status, 'due_date': cow.due_date.isoformat() if cow.due_date else None,
        **computed_fields,
    }
    payload['status'] = payload['current_status'] # Alias for frontend compatibility
    return jsonify(payload), 200


@operations_bp.route('/api/herd/<int:cow_id>/photo', methods=['POST'])
@operations_bp.route('/api/animals/<int:cow_id>/photo', methods=['POST'])
@operations_bp.route('/api/animals/<string:animal_id>/photo', methods=['POST'])
@jwt_required()
@role_required(Role.FARMER)
def upload_animal_photo(cow_id=None, animal_id=None):
    tenant_id = _get_tenant_id_from_claims()
    if tenant_id is None:
        return jsonify({'error': 'Missing or invalid tenant in token.'}), 400
    identifier = cow_id if cow_id is not None else animal_id
    cow = _resolve_cow_by_identifier(identifier, tenant_id)
    if not cow:
        return jsonify({'error': 'Animal not found.'}), 404

    file_storage = request.files.get('file') or request.files.get('photo')
    from app.services.animal_photo_service import AnimalPhotoService
    try:
        AnimalPhotoService.upload_photo(tenant_id=tenant_id, cow=cow, file_storage=file_storage)
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400

    return jsonify(_serialize_animal_summary(cow, tenant_id)), 200


@operations_bp.route('/api/herd/<int:cow_id>/photo', methods=['DELETE'])
@operations_bp.route('/api/animals/<int:cow_id>/photo', methods=['DELETE'])
@operations_bp.route('/api/animals/<string:animal_id>/photo', methods=['DELETE'])
@jwt_required()
@role_required(Role.FARMER)
def remove_animal_photo(cow_id=None, animal_id=None):
    tenant_id = _get_tenant_id_from_claims()
    if tenant_id is None:
        return jsonify({'error': 'Missing or invalid tenant in token.'}), 400
    identifier = cow_id if cow_id is not None else animal_id
    cow = _resolve_cow_by_identifier(identifier, tenant_id)
    if not cow:
        return jsonify({'error': 'Animal not found.'}), 404

    from app.services.animal_photo_service import AnimalPhotoService
    AnimalPhotoService.remove_photo(tenant_id=tenant_id, cow=cow)

    return jsonify(_serialize_animal_summary(cow, tenant_id)), 200


@operations_bp.route('/api/herd/genetic-progress', methods=['GET'])
@jwt_required()
@role_required(Role.FARMER, Role.VET)
def get_herd_genetic_progress():
    """
    Compare projected milk-volume genetics for daughters and their dams.

    Each point is grouped by the daughter's birth year and only includes pairs
    where both animals have a milk_volume trait score.
    """
    tenant_id = _get_tenant_id_from_claims()
    if tenant_id is None:
        return jsonify({'error': 'Missing or invalid tenant in token.'}), 400

    try:
        mother = aliased(Cow)
        daughter_profile = aliased(GeneticProfile)
        mother_profile = aliased(GeneticProfile)
        daughter_score = aliased(GeneticTraitScore)
        mother_score = aliased(GeneticTraitScore)

        progress_data = db.session.query(
            func.extract('year', Cow.date_of_birth).label('year'),
            func.avg(daughter_score.value).label('daughters_yield'),
            func.avg(mother_score.value).label('mothers_yield'),
            func.count(Cow.id).label('sample_size'),
        ).join(
            mother, Cow.dam_id == mother.id,
        ).join(
            daughter_profile,
            (daughter_profile.cow_id == Cow.id)
            & (daughter_profile.tenant_id == tenant_id),
        ).join(
            daughter_score, daughter_score.profile_id == daughter_profile.id,
        ).join(
            GeneticTraitDefinition,
            (GeneticTraitDefinition.id == daughter_score.trait_definition_id)
            & (GeneticTraitDefinition.name == 'milk_volume'),
        ).join(
            mother_profile,
            (mother_profile.cow_id == mother.id)
            & (mother_profile.tenant_id == tenant_id),
        ).join(
            mother_score,
            (mother_score.profile_id == mother_profile.id)
            & (mother_score.trait_definition_id == daughter_score.trait_definition_id),
        ).filter(
            Cow.tenant_id == tenant_id,
            mother.tenant_id == tenant_id,
            Cow.date_of_birth.isnot(None),
        ).group_by(
            func.extract('year', Cow.date_of_birth)
        ).order_by(
            func.extract('year', Cow.date_of_birth).asc()
        ).all()

        payload = [
            {
                'year': int(row.year),
                'daughters_yield': round(float(row.daughters_yield), 2),
                'mothers_yield': round(float(row.mothers_yield), 2),
                'sample_size': int(row.sample_size),
            }
            for row in progress_data
            if row.year is not None and row.daughters_yield is not None and row.mothers_yield is not None
        ]
        return jsonify({
            'items': payload,
            'meta': {
                'trait': 'milk_volume',
                'unit': 'liters/day',
                'requires': ['daughter_date_of_birth', 'daughter_dam_id', 'daughter_milk_volume', 'dam_milk_volume'],
                'pair_count': sum(item['sample_size'] for item in payload),
            },
        }), 200
    except Exception as e:
        current_app.logger.error(f"Failed to calculate genetic progress for tenant {tenant_id}: {str(e)}")
        return jsonify({'error': 'An internal error occurred while calculating genetic progress.'}), 500


@operations_bp.route('/api/herd/<int:cow_id>', methods=['DELETE'])
@operations_bp.route('/api/animals/<int:cow_id>', methods=['DELETE'])
@operations_bp.route('/api/animals/<string:animal_id>', methods=['DELETE'])
@jwt_required()
@role_required(Role.FARMER)
def delete_herd_member(cow_id=None, animal_id=None):
    tenant_id = _get_tenant_id_from_claims()
    if tenant_id is None:
        return jsonify({'error': 'Missing or invalid tenant in token.'}), 400
    identifier = cow_id if cow_id is not None else animal_id
    cow = _resolve_cow_by_identifier(identifier, tenant_id)
    if not cow:
        return jsonify({'error': 'Animal not found.'}), 404

    # Soft delete: mark the cow as inactive instead of deleting the record.
    cow.is_active = False

    # Free up the tag number for reuse by suffixing the archived record's tag.
    # This preserves the unique constraint on (tenant_id, tag_number) for active cows.
    timestamp = int(time.time())
    cow.tag_number = f"{cow.tag_number}_archived_{timestamp}"

    db.session.commit()

    return jsonify({'message': 'Animal successfully archived and tag number freed.', 'id': cow.id}), 200


@operations_bp.route('/api/animals/<int:cow_id>/milk-history', methods=['GET'])
@operations_bp.route('/api/animals/<string:cow_id_or_tag>/milk-history', methods=['GET'])
@jwt_required()
@role_required(Role.FARMER, Role.FARM_HAND, Role.VET)
def animal_milk_history(cow_id_or_tag):
    tenant_id = _get_tenant_id_from_claims()
    if tenant_id is None:
        return jsonify({'error': 'Missing or invalid tenant in token.'}), 400
    cow = _resolve_cow_by_identifier(cow_id_or_tag, tenant_id)
    if not cow:
        return jsonify({'error': 'Animal not found.'}), 404

    query = db.session.query(
        MilkLog,
        User.name,
    ).select_from(MilkLog).outerjoin(
        User, User.id == MilkLog.recorded_by
    ).filter(MilkLog.cow_id == cow.id, MilkLog.tenant_id == tenant_id)

    try:
        start_dt, end_dt, end_is_exclusive = _parse_history_date_bounds(
            request.args.get('start_date'),
            request.args.get('end_date'),
        )
    except ValueError:
        return jsonify({'error': 'start_date and end_date must be ISO format.'}), 400

    if start_dt is not None:
        query = query.filter(MilkLog.timestamp >= start_dt)
    if end_dt is not None:
        comparator = MilkLog.timestamp < end_dt if end_is_exclusive else MilkLog.timestamp <= end_dt
        query = query.filter(comparator)

    summary_logs = [log for log, _ in query.all()]
    session_count = len(summary_logs)
    total_logged = sum(float(log.amount_liters or 0) for log in summary_logs)
    average_yield, peak_yield = _compute_daily_average_and_peak(summary_logs)

    query = query.order_by(MilkLog.timestamp.desc())
    paginated = _paginate_query(query)

    sessions = [
        _serialize_milk_session(log, cow_tag=cow.tag_number, cow_name=cow.name, milker_name=milker_name)
        for log, milker_name in paginated.items
    ]
    return jsonify({
        'animal': _serialize_animal_summary(cow, tenant_id),
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

    created_by = get_jwt_identity()
    try:
        created_by = int(created_by) if created_by is not None else None
    except (TypeError, ValueError):
        created_by = None

    # Calving / birth events have rich domain side-effects (status, lactation, breeding log, calf)
    if event_type.lower() in ('calving', 'birth'):
        from app.services.calving_service import CalvingService
        calving_payload = {
            'calving_date': event_date_raw,
            'notes': description,
            'title': title,
            **data,
            **(event_data if isinstance(event_data, dict) else {}),
        }
        res_payload, status_code = CalvingService.record_calving(
            tenant_id=tenant_id,
            cow_id_or_tag=cow.id,
            data=calving_payload,
            user_id=created_by,
        )
        # Return the full atomic result (mother/calf/breeding_log/lactation_cycle/event)
        # so this fallback route matches the dedicated /calving endpoint's response contract.
        return jsonify(res_payload), status_code

    event_date = datetime.now(timezone.utc)
    if event_date_raw:
        try:
            event_date = datetime.fromisoformat(str(event_date_raw))
            if event_date.tzinfo is None:
                event_date = event_date.replace(tzinfo=timezone.utc)
        except ValueError:
            return jsonify({'error': 'event_date must be ISO format.'}), 400

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


@operations_bp.route('/api/animals/<string:animal_id>/calving', methods=['POST'])
@operations_bp.route('/api/cows/<string:animal_id>/calving', methods=['POST'])
@operations_bp.route('/api/herd/<string:animal_id>/calving', methods=['POST'])
@operations_alias_bp.route('/api/animals/<string:animal_id>/calving', methods=['POST'])
@operations_alias_bp.route('/api/cows/<string:animal_id>/calving', methods=['POST'])
@operations_alias_bp.route('/api/herd/<string:animal_id>/calving', methods=['POST'])
@jwt_required()
@role_required(Role.FARMER, Role.FARM_HAND, Role.VET)
def log_animal_calving(animal_id):
    tenant_id = _get_tenant_id_from_claims()
    if tenant_id is None:
        return jsonify({'error': 'Missing or invalid tenant in token.'}), 400

    data = request.get_json(silent=True) or {}
    created_by = get_jwt_identity()
    try:
        created_by = int(created_by) if created_by is not None else None
    except (TypeError, ValueError):
        created_by = None

    from app.services.calving_service import CalvingService
    response_payload, status_code = CalvingService.record_calving(
        tenant_id=tenant_id,
        cow_id_or_tag=animal_id,
        data=data,
        user_id=created_by,
    )
    return jsonify(response_payload), status_code


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
        base_query = MilkLog.query.filter_by(tenant_id=tenant_id)
        status_filter = request.args.get('status')
        if status_filter == 'anomaly':
            base_query = base_query.filter(MilkLog.anomaly_flag.is_(True))

        all_rows = base_query.all()
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

        paginated_query = db.session.query(
            MilkLog,
            Cow.tag_number,
            Cow.name,
            User.name
        ).select_from(MilkLog).join(
            Cow, Cow.id == MilkLog.cow_id
        ).outerjoin(
            User, User.id == MilkLog.recorded_by
        ).filter(MilkLog.tenant_id == tenant_id)

        if status_filter == 'anomaly':
            paginated_query = paginated_query.filter(MilkLog.anomaly_flag.is_(True))

        paginated_query = paginated_query.order_by(MilkLog.timestamp.desc())
        paginated = _paginate_query(paginated_query)
        rows = [
            _serialize_milk_session(log, cow_tag=cow_tag, cow_name=cow_name, milker_name=milker_name)
            for log, cow_tag, cow_name, milker_name in paginated.items
        ]
        return jsonify({'items': rows, 'meta': {'page': paginated.page, 'per_page': paginated.per_page, 'total': paginated.total, 'pages': paginated.pages}, 'summary': summary}), 200
    if request.method == 'POST' and log_id is None:
        data = request.get_json() or {}
        cow_identifier = data.get('cow_id')
        amount = data.get('amount')
        session = data.get('session')
        if not cow_identifier or amount is None or not session:
            return jsonify({'error': 'cow_id, amount, and session are required.'}), 400
        cow = _resolve_cow_by_identifier(cow_identifier, tenant_id)
        if not cow:
            return jsonify({'error': 'Cow not found.'}), 404
        user_id = get_jwt_identity()
        try:
            amount_float = float(amount)
            if amount_float <= 0:
                return jsonify({'error': 'Amount must be greater than 0.'}), 400
        except ValueError:
            return jsonify({'error': 'Amount must be a valid number.'}), 400
        milking_date, date_error = _parse_milking_date(data)
        if date_error:
            return date_error
        response_data, status_code = ProductionService.log_daily_yield(cow.id, amount_float, session, user_id, tenant_id, milking_date=milking_date)
        return _augment_yield_response(response_data, status_code, tenant_id)
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
        average, peak = _compute_daily_average_and_peak(cow_sessions)

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
        if 'amount' in data and data.get('amount') is not None:
            try:
                amount_float = float(data['amount'])
                if amount_float <= 0:
                    return jsonify({'error': 'Amount must be greater than 0.'}), 400
            except (TypeError, ValueError):
                return jsonify({'error': 'Amount must be a valid number.'}), 400
            log.amount_liters = amount_float
        if data.get('session'):
            log.session = data['session']
        milking_date, date_error = _parse_milking_date(data)
        if date_error:
            return date_error
        if milking_date:
            current_time = log.timestamp.timetz() if log.timestamp else datetime.now(timezone.utc).timetz()
            log.timestamp = datetime.combine(milking_date, current_time)
        db.session.commit()
        return jsonify({
            'id': log.id,
            'cow_id': log.cow_id,
            'amount': float(log.amount_liters),
            'session': log.session,
            'milkingDate': log.timestamp.date().isoformat() if log.timestamp else None,
            'status': _milk_log_status(log),
        }), 200
    if request.method == 'DELETE':
        log = db.session.query(MilkLog).filter_by(id=log_id, tenant_id=tenant_id).first()
        if not log:
            return jsonify({
                'message': 'Production record is already deleted.',
                'id': log_id,
                'already_deleted': True,
            }), 200
        db.session.delete(log)
        db.session.commit()
        return jsonify({
            'message': 'Production record deleted successfully.',
            'id': log_id,
            'already_deleted': False,
        }), 200


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

    log.verified_by = int(get_jwt_identity())
    log.verified_at = datetime.now(timezone.utc)
    log.status = MilkLog.STATUS_VERIFIED
    db.session.commit()

    # Re-fetch with related data for serialization to provide a rich response
    result = db.session.query(
        MilkLog,
        Cow.tag_number,
        Cow.name,
        User.name
    ).select_from(MilkLog).join(
        Cow, Cow.id == MilkLog.cow_id
    ).outerjoin(
        User, User.id == MilkLog.recorded_by
    ).filter(MilkLog.id == log.id).first()

    if result:
        log_res, cow_tag, cow_name, milker_name = result
        return jsonify(_serialize_milk_session(log_res, cow_tag=cow_tag, cow_name=cow_name, milker_name=milker_name)), 200

    return jsonify(_serialize_milk_session(log)), 200


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

    # Base query for today's milk logs
    base_milk_log_query = db.session.query(MilkLog).filter(
        MilkLog.tenant_id == tenant_id,
        MilkLog.timestamp >= start_of_day,
        MilkLog.timestamp < next_day
    )

    # Aggregated milk volumes and cow count
    production_stats = base_milk_log_query.with_entities(
        func.coalesce(func.sum(MilkLog.amount_liters), 0),
        func.coalesce(func.sum(case((MilkLog.is_saleable.is_(True), MilkLog.amount_liters), else_=0)), 0),
        func.count(func.distinct(MilkLog.cow_id))
    ).first()

    cows_milked = production_stats[2] or 0
    milk_inventory = MilkInventoryRepository.summary_for_date(tenant_id=tenant_id, inventory_date=today)
    total_liters = milk_inventory['produced_liters']
    saleable_liters = milk_inventory['medically_saleable_liters']

    # Aggregated status counts
    status_counts = base_milk_log_query.with_entities(
        func.count(MilkLog.id),
        func.sum(case((MilkLog.status == MilkLog.STATUS_VERIFIED, 1), else_=0)),
        func.sum(case((MilkLog.status == MilkLog.STATUS_FLAGGED, 1), else_=0)),
        func.sum(case((MilkLog.status == MilkLog.STATUS_ISOLATED, 1), else_=0)),
        func.sum(case((MilkLog.status == MilkLog.STATUS_RECORDED, 1), else_=0))
    ).first()

    total_records = status_counts[0] or 0
    verified_count = status_counts[1] or 0
    flagged_count = status_counts[2] or 0
    isolated_count = status_counts[3] or 0
    recorded_count = status_counts[4] or 0

    # Determine overall verification status
    status = 'No Data'
    if total_records > 0:
        # If there are any non-verified entries, the day is pending.
        pending_verification_count = flagged_count + isolated_count + recorded_count
        status = 'Pending Verification' if pending_verification_count > 0 else 'Verified'

    from app.models.finance import SalesLedger, Delivery

    # Sold liters should mirror the milk inventory report sources.
    sold_liters_buyers = db.session.query(func.coalesce(func.sum(SalesLedger.liters_sold), 0)).filter(
        SalesLedger.tenant_id == tenant_id,
        SalesLedger.date == today,
    ).scalar() or 0

    sold_liters_customers = db.session.query(func.coalesce(func.sum(Delivery.billable_liters), 0)).filter(
        Delivery.tenant_id == tenant_id,
        Delivery.date == today,
    ).scalar() or 0

    total_sold_liters = float(sold_liters_buyers) + float(sold_liters_customers)
    remaining_milk_liters = float(milk_inventory['remaining_liters'])

    # --- Financial Calculations (delegated to FinanceService for consistency) ---
    financial_summary = FinanceService.get_daily_financial_summary(tenant_id, for_date=today)
    transaction_revenue_total = financial_summary['revenue_total_kes']
    feed_cost = financial_summary['feed_cost_total_kes']
    total_costs = financial_summary.get('total_costs_kes', feed_cost)
    net_margin = financial_summary['net_margin_kes']

    # Keep dashboard revenue aligned with milk-sales sources used in reporting.
    buyer_sales_value = db.session.query(func.coalesce(func.sum(SalesLedger.total_amount), 0)).filter(
        SalesLedger.tenant_id == tenant_id,
        SalesLedger.date == today,
    ).scalar() or 0

    customer_sales_value = db.session.query(func.coalesce(func.sum(Delivery.total_price), 0)).filter(
        Delivery.tenant_id == tenant_id,
        Delivery.date == today,
    ).scalar() or 0

    report_sales_revenue_total = float(buyer_sales_value) + float(customer_sales_value)
    # Non-double-counting mode: revenue total is sourced from accounting transactions.
    revenue_total = float(transaction_revenue_total)

    avg_per_cow = round(float(total_liters) / int(cows_milked), 1) if cows_milked else 0.0
    profit_per_liter = float(net_margin / saleable_liters) if saleable_liters > 0 else 0.0

    payload = {
        'date': today.isoformat(),
        'production_total_liters': float(total_liters),
        'saleable_liters': float(saleable_liters),
        'total_sold_liters': total_sold_liters,
        'calf_fed_liters': float(milk_inventory['disposition_liters']),
        'personal_consumption_liters': float(
            milk_inventory['customer_delivery_liters'] - Decimal(str(sold_liters_customers))
        ),
        'remaining_milk_liters': remaining_milk_liters,
        'revenue_total_kes': float(revenue_total),
        'feed_cost_total_kes': float(feed_cost),
        'total_costs_kes': float(total_costs),
        'net_margin_kes': float(net_margin),
        'revenue_breakdown': {
            'transaction_revenue_kes': float(transaction_revenue_total),
            'report_sales_revenue_kes': report_sales_revenue_total,
            'mode': 'non_double_counting',
        },
        'operational_alerts': int(flagged_count),
        'cows_milked': int(cows_milked),
        'avg_per_cow': avg_per_cow,
        'profit_per_liter': profit_per_liter,
        'status': status,
        'status_counts': {
            'total': int(total_records),
            'verified': int(verified_count),
            'flagged': int(flagged_count),
            'isolated': int(isolated_count),
            'recorded': int(recorded_count),
        },
        # Backward-compatibility aliases
        'total_liters': float(total_liters),
        'total_milk_today': float(total_liters),
        'cowsMilked': int(cows_milked),
        'avgPerCow': avg_per_cow,
        'profitPerLiter': profit_per_liter,
        'anomaly_count': int(flagged_count),
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
    def serialize_alert(alert):
        cow = CowRepository.get_by_id(alert.cow_id, tenant_id=tenant_id)
        return {
            'id': alert.id,
            'cow_id': alert.cow_id,
            'cow_tag': cow.tag_number if cow else None,
            'cow_name': cow.name if cow else None,
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

    rows = [serialize_alert(alert) for alert in paginated.items]
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
            'sire_pta_scores': row.sire_pta_scores,
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
    cow_identifier = data.get('cow_id')
    amount = data.get('amount')
    session = data.get('session')
    if not cow_identifier or amount is None or not session:
        return jsonify({'error': 'cow_id, amount, and session are required.'}), 400
    user_id = get_jwt_identity()
    tenant_id = _get_tenant_id_from_claims()
    cow = _resolve_cow_by_identifier(cow_identifier, tenant_id)
    if not cow:
        return jsonify({'error': 'Cow not found.'}), 404
    try:
        amount_float = float(amount)
        if amount_float <= 0:
            return jsonify({'error': 'Amount must be greater than 0.'}), 400
    except ValueError:
        return jsonify({'error': 'Amount must be a valid number.'}), 400
    milking_date, date_error = _parse_milking_date(data)
    if date_error:
        return date_error
    response_data, status_code = ProductionService.log_daily_yield(cow.id, amount_float, session, user_id, tenant_id, milking_date=milking_date)
    return _augment_yield_response(response_data, status_code, tenant_id)


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
    return delete_herd_member(cow_id=cow_id)


@operations_alias_bp.route('/api/animals/<int:cow_id>', methods=['DELETE'])
@operations_alias_bp.route('/api/animals/<string:animal_id>', methods=['DELETE'])
def delete_animal_alias(cow_id=None, animal_id=None):
    return delete_herd_member(cow_id=cow_id, animal_id=animal_id)


@operations_alias_bp.route('/api/herd/<int:cow_id>/photo', methods=['POST'])
@operations_alias_bp.route('/api/animals/<int:cow_id>/photo', methods=['POST'])
@operations_alias_bp.route('/api/animals/<string:animal_id>/photo', methods=['POST'])
def upload_animal_photo_alias(cow_id=None, animal_id=None):
    return upload_animal_photo(cow_id=cow_id, animal_id=animal_id)


@operations_alias_bp.route('/api/herd/<int:cow_id>/photo', methods=['DELETE'])
@operations_alias_bp.route('/api/animals/<int:cow_id>/photo', methods=['DELETE'])
@operations_alias_bp.route('/api/animals/<string:animal_id>/photo', methods=['DELETE'])
def remove_animal_photo_alias(cow_id=None, animal_id=None):
    return remove_animal_photo(cow_id=cow_id, animal_id=animal_id)


@operations_alias_bp.route('/api/herd/genetic-progress', methods=['GET'])
def get_herd_genetic_progress_alias():
    return get_herd_genetic_progress()


@operations_alias_bp.route('/api/animals/<string:cow_id>/milk-history', methods=['GET'])
def animal_milk_history_alias(cow_id): # The function parameter should also match the route's variable name
    return animal_milk_history(cow_id) # Pass the cow_id to the main function


@operations_alias_bp.route('/api/production/history/<string:cow_id>', methods=['GET'])
def production_history_alias(cow_id):
    return animal_milk_history(cow_id)


@operations_alias_bp.route('/api/production/yield', methods=['GET', 'POST'])
@operations_alias_bp.route('/api/production/yield/<int:log_id>', methods=['GET', 'PATCH', 'DELETE'])
def production_yield_alias(log_id=None):
    return production_yield_legacy(log_id)


@operations_alias_bp.route('/api/production/yield/<int:log_id>/verify', methods=['PATCH'])
def verify_production_yield_alias(log_id):
    return verify_production_yield(log_id)
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
