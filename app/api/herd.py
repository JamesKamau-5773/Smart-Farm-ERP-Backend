from flask import Blueprint, jsonify
from flask_jwt_extended import jwt_required

from app.models.livestock import Cow
from app.models.user import Role
from app.utils import get_tenant_id_from_context
from app.services.cow_status_service import CowStatusService
from app.utils.decorators import role_required

herd_bp = Blueprint('herd', __name__)


def _serialize_cow(cow: Cow) -> dict:
    """
    Serializes a Cow object for API responses.

    Crucially, it uses the `cow.current_status` property to ensure the displayed
    status is always accurate and derived from the authoritative CowStatusService.
    """
    computed_status = CowStatusService.compute_current_status(cow)
    return {
        'id': cow.id,
        'name': cow.name,
        'tag_number': cow.tag_number,
        'gender': cow.gender,
        'date_of_birth': cow.date_of_birth.isoformat() if cow.date_of_birth else None,
        'age_in_months': cow.age_in_months,

        # The new, accurate status derived from business logic.
        # The frontend should use this field as the source of truth.
        "current_status": computed_status,

        # We also return the underlying data for full context on the frontend.
        "pregnancy_status": cow.pregnancy_status,
        "due_date": cow.due_date.isoformat() if cow.due_date else None,
        "last_calving_date": cow.last_calving_date.isoformat() if cow.last_calving_date else None,
        "last_calved": cow.last_calving_date.isoformat() if cow.last_calving_date else None,

        # The old, potentially incorrect status. Can be used for comparison during
        # transition and then removed from the API response.
        "status": cow.status,
    }


@herd_bp.route('/cows', methods=['GET'])
@jwt_required()
@role_required(Role.FARMER, Role.FARM_HAND)
def get_herd_list():
    """
    Returns a list of all cows for the tenant, with their statuses
    dynamically and accurately calculated.
    """
    tenant_id = get_tenant_id_from_context()
    if not tenant_id:
        return jsonify({'error': 'Tenant context is missing.'}), 400

    # In a real app, you'd add pagination here.
    cows = Cow.query.filter_by(tenant_id=tenant_id).order_by(Cow.name).all()

    serialized_cows = [_serialize_cow(cow) for cow in cows]

    return jsonify(serialized_cows), 200
