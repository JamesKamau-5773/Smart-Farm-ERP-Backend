from flask import Blueprint, request, jsonify, current_app, g
from flask_jwt_extended import jwt_required

from app import db
from app.models.livestock import DailyTaskLog, HerdsmanRoutineTemplate
from app.models.user import Role, User
from app.utils.decorators import require_tenant_context
from app.utils import get_tenant_id_from_context

herdsman_bp = Blueprint('herdsman', __name__)


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

    current_tenant_id = get_tenant_id_from_context()
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
    tenant_id = get_tenant_id_from_context()
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
    tenant_id = get_tenant_id_from_context()
    if tenant_id is None:
        return jsonify({"error": "Missing or invalid tenant context."}), 400

    tasks_data = request.get_json()
    if not isinstance(tasks_data, list):
        return jsonify({'error': 'Request body must be a JSON array of routine tasks.'}), 400

    from datetime import time
    new_routines = []

    try:
        # Atomically replace the old routine plan for this tenant
        HerdsmanRoutineTemplate.query.filter_by(tenant_id=tenant_id).delete()

        for index, task_data in enumerate(tasks_data):
            if not isinstance(task_data, dict):
                raise ValueError(f"Invalid item at index {index}: must be an object.")

            # As you noted, the payload uses 'title', so we'll check for both.
            task_title = (task_data.get('task_title') or task_data.get('title') or '').strip()
            task_description = (task_data.get('task_description') or task_data.get('description') or task_title).strip()

            if not task_title:
                raise ValueError(f"Missing 'title' for task at index {index}.")

            # The frontend should send 'start_time' and 'end_time' in 'HH:MM:SS' format.
            start_time_str = task_data.get('start_time')
            end_time_str = task_data.get('end_time')

            if not start_time_str or not end_time_str:
                 raise ValueError(f"Missing 'start_time' or 'end_time' for task '{task_title}'. Expected 'HH:MM:SS' format.")

            routine = HerdsmanRoutineTemplate(
                tenant_id=tenant_id,
                start_time=time.fromisoformat(start_time_str),
                end_time=time.fromisoformat(end_time_str),
                task_title=task_title,
                task_description=task_description,
                notes=task_data.get('notes'),
                checklist_items=task_data.get('checklist_items') or [],
                display_order=task_data.get('display_order', index),
                is_active=bool(task_data.get('is_active', True)),
            )
            db.session.add(routine)

        db.session.commit()
        return jsonify({'message': f'Successfully saved {len(tasks_data)} routine tasks.'}), 201

    except (ValueError, TypeError) as e:
        db.session.rollback()
        return jsonify({'error': f'Invalid data format: {str(e)}'}), 400
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Failed to save routine plan: {str(e)}")
        return jsonify({'error': 'An internal error occurred while saving the routine plan.'}), 500
