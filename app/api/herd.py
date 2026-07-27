from flask import Blueprint, jsonify
from flask_jwt_extended import jwt_required
from sqlalchemy.exc import IntegrityError

from app import db
from app.models.livestock import Cow
from app.models.user import Role
from app.utils import get_tenant_id_from_context
from app.utils.decorators import role_required

herd_bp = Blueprint('herd', __name__)


# Assume other herd endpoints (GET, POST, PATCH for cows) exist here.


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