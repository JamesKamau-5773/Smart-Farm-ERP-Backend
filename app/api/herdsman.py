from flask import Blueprint, request, jsonify, current_app, g
from flask_jwt_extended import jwt_required

from app import db
from app.models.livestock import DailyTaskLog, HerdsmanRoutineTemplate
from app.models.user import Role, User
from app.utils.decorators import require_tenant_context
from app.utils.jwt_payload import parse_public_int_id

herdsman_bp = Blueprint('herdsman', __name__)

def _get_current_tenant_id():
    tenant_public_id = getattr(g, 'tenant_id', None)
    if not tenant_public_id:
        return None

    try:
        return parse_public_int_id(tenant_public_id, 'tenant_')
    except (TypeError, ValueError):
        return None


@herdsman_bp.route('/api/v1/tasks/<int:routine_id>/complete', methods=['POST'])
@jwt_required()
@require_tenant_context
def mark_task_complete(routine_id):
    data = request.get_json() or {}

    tenant_id = data.get('tenant_id')
    user_id = data.get('user_id')

    if tenant_id is None or user_id is None:
        return jsonify({"error": "tenant_id and user_id are required"}), 400

    try:
        tenant_id = int(tenant_id)
        user_id = int(user_id)
    except (TypeError, ValueError):
        return jsonify({"error": "tenant_id and user_id must be integers"}), 400

    current_tenant_id = _get_current_tenant_id()
    if current_tenant_id is None:
        return jsonify({"error": "Missing or invalid tenant context."}), 400

    if tenant_id != current_tenant_id:
        return jsonify({"error": "Tenant context mismatch."}), 403

    user = db.session.get(User, user_id)
    if not user or user.tenant_id != tenant_id or not user.is_active:
        return jsonify({"error": "User not found or inactive for this tenant."}), 404

    if user.role not in {Role.FARMER, Role.FARM_HAND}:
        return jsonify({"error": "User is not authorized to complete herdsman tasks."}), 403

    issue_tag = data.get('issue_tag')
    status = 'Deviated' if issue_tag and str(issue_tag).lower() != 'none' else 'Completed'
    issue_tag = issue_tag if status == 'Deviated' else 'None'

    try:
        valid_routine = db.session.query(HerdsmanRoutineTemplate.id).filter_by(
            id=routine_id,
            tenant_id=tenant_id,
        ).one_or_none()
        if not valid_routine:
            return jsonify({"error": "Routine not found or does not belong to this tenant."}), 404

        new_log = DailyTaskLog(
            tenant_id=tenant_id,
            routine_id=routine_id,
            herdsman_id=user_id,
            issue_tag=issue_tag,
            status=status,
        )
        db.session.add(new_log)
        db.session.commit()

        actual_time = new_log.completed_at
        return jsonify({"message": "Logged successfully.", "recorded_time": actual_time}), 200

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Task completion failed for routine {routine_id}: {str(e)}")
        return jsonify({"error": "Failed to log task completion."}), 500
