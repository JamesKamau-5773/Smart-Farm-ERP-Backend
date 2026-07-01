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


@herdsman_bp.route('/api/routine/plans', methods=['GET'])
@jwt_required()
@require_tenant_context
def list_routine_plans():
    tenant_id = _get_current_tenant_id()
    if tenant_id is None:
        return jsonify({"error": "Missing or invalid tenant context."}), 400
    routines = HerdsmanRoutineTemplate.query.filter_by(tenant_id=tenant_id).order_by(HerdsmanRoutineTemplate.display_order.asc()).all()
    return jsonify([
        {
            'id': routine.id,
            'tenant_id': routine.tenant_id,
            'start_time': routine.start_time.isoformat() if routine.start_time else None,
            'end_time': routine.end_time.isoformat() if routine.end_time else None,
            'task_title': routine.task_title,
            'task_description': routine.task_description,
            'notes': routine.notes,
            'checklist_items': routine.checklist_items or [],
            'display_order': routine.display_order,
            'is_active': routine.is_active,
        }
        for routine in routines
    ]), 200


@herdsman_bp.route('/api/routine/plans', methods=['POST'])
@jwt_required()
@require_tenant_context
def save_routine_plan():
    tenant_id = _get_current_tenant_id()
    if tenant_id is None:
        return jsonify({"error": "Missing or invalid tenant context."}), 400
    data = request.get_json() or {}
    task_title = (data.get('task_title') or '').strip()
    task_description = (data.get('task_description') or '').strip()
    if not task_title or not task_description:
        return jsonify({'error': 'task_title and task_description are required.'}), 400
    from datetime import time
    routine = HerdsmanRoutineTemplate(
        tenant_id=tenant_id,
        start_time=time.fromisoformat(data.get('start_time') or '06:00:00'),
        end_time=time.fromisoformat(data.get('end_time') or '07:00:00'),
        task_title=task_title,
        task_description=task_description,
        notes=data.get('notes'),
        checklist_items=data.get('checklist_items'),
        display_order=int(data.get('display_order', 0)),
        is_active=bool(data.get('is_active', True)),
    )
    db.session.add(routine)
    db.session.commit()
    return jsonify({'id': routine.id, 'task_title': routine.task_title}), 201
