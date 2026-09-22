from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required
from datetime import datetime
from sqlalchemy.exc import IntegrityError

from app import db
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

@herd_bp.route('/<int:cow_id>', methods=['PATCH'])
@jwt_required()
@role_required(Role.FARMER, Role.FARM_HAND)
def update_cow(cow_id):
    """
    Updates an existing cow record.
    Handles the mapping of 'current_status' from frontend to 'status' in the database.
    """
    data = request.get_json()
    tenant_id = get_tenant_id_from_context()
    if tenant_id is None:
        return jsonify({'error': 'Missing or invalid tenant context.'}), 400

    cow = db.session.query(Cow).filter_by(id=cow_id, tenant_id=tenant_id).first()
    if not cow:
        return jsonify({'error': 'Cow not found.'}), 404

    try:
        # Update fields if they are present in the request payload
        if 'tag_number' in data:
            cow.tag_number = data['tag_number']
        if 'name' in data:
            cow.name = data['name']
        if 'breed_status' in data:
            cow.breed_status = data['breed_status']
        if 'date_of_birth' in data and data['date_of_birth']:
            cow.date_of_birth = datetime.strptime(data['date_of_birth'], '%Y-%m-%d').date()

        # Map frontend's 'current_status' to backend's 'status' column
        if 'current_status' in data:
            cow.status = data['current_status']

        if 'sire_name' in data:
            cow.sire_name = data['sire_name']
        if 'dam_id' in data:
            # Ensure dam_id is set to None if an empty string is passed (for optional FKs)
            cow.dam_id = data['dam_id'] if data['dam_id'] != '' else None

        if 'is_hardlocked' in data:
            cow.is_hardlocked = data['is_hardlocked']
        if 'is_active' in data:
            cow.is_active = data['is_active']
        if 'last_calving_date' in data and data['last_calving_date']:
            cow.last_calving_date = datetime.strptime(data['last_calving_date'], '%Y-%m-%d').date()
        if 'pregnancy_status' in data:
            cow.pregnancy_status = data['pregnancy_status']
        if 'due_date' in data and data['due_date']:
            cow.due_date = datetime.strptime(data['due_date'], '%Y-%m-%d').date()

        db.session.commit()
        return jsonify(_serialize_cow(cow)), 200
    except IntegrityError:
        db.session.rollback()
        return jsonify({'error': 'A cow with this tag number already exists for your tenant.'}), 409
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'An unexpected error occurred: {str(e)}'}), 500

@herd_bp.route('/<int:cow_id>', methods=['DELETE'])
@jwt_required()
@role_required(Role.FARMER)
def delete_cow(cow_id):
    """
    Deletes a cow record.
    This is a hard delete. It will fail if the cow has dependent records
    like milk logs or medical records. In that case, the user should
    change the cow's status to 'Culled' or 'Sold' instead.
    """
    tenant_id = get_tenant_id_from_context()
    if tenant_id is None:
        return jsonify({'error': 'Missing or invalid tenant context.'}), 400

    cow = db.session.query(Cow).filter_by(id=cow_id, tenant_id=tenant_id).first()
    if not cow:
        return jsonify({'error': 'Cow not found.'}), 404

    try:
        db.session.delete(cow)
        db.session.commit()
        return jsonify({'message': f'Cow with tag "{cow.tag_number}" deleted successfully.'}), 200
    except IntegrityError:
        db.session.rollback()
        return jsonify({
            'error': 'Cannot delete this cow because it has associated records (e.g., milk logs, medical history). Consider changing its status to "Culled" or "Sold" instead.'
        }), 409
