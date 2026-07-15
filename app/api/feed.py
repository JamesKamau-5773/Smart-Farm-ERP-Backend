from flask import Blueprint, request, jsonify, g
from flask_jwt_extended import jwt_required, get_jwt
from app.services.feed_frequency_helper import FeedFrequencyHelper
from app.services.yield_target_service import YieldTargetService
from app.services.herd_feeding_plan_service import HerdFeedingPlanService
from app.utils.jwt_payload import parse_public_int_id

feed_bp = Blueprint('feed', __name__)


def _get_tenant_id_from_claims():
    """Extract and parse tenant_id from JWT claims."""
    claims = get_jwt()
    tenant_public_id = claims.get('tenant_id')
    if not tenant_public_id:
        return None
    try:
        return parse_public_int_id(tenant_public_id, 'tenant_')
    except (TypeError, ValueError):
        return None


@feed_bp.route('/api/v1/feed/calculate-schedule', methods=['POST'])
def calculate_schedule():
    """Calculate milking schedule with support for both herd-level and per-cow targets.
    
    Payload:
    {
        "target_liters": number,
        "baseline_herd_meal_kg": number (optional, default 4.0),
        "milking_frequency": int (optional, 2-4),
        "animal_targets": [{"cow_id": int, "target_liters": number}] (optional, NEW),
        "lactating_cow_ids": [int] (optional, NEW),
        "target_mode": str (optional, "herd"|"per_cow"|"hybrid", default "herd")
    }
    
    If target_mode="per_cow" and animal_targets provided:
        Uses per-cow targets (sums them for calculation)
    Otherwise:
        Uses herd-level target_liters (backward compatible)
    """
    data = request.get_json() or {}
    
    # Required fields
    target_liters = data.get('target_liters')
    
    # Optional fields (support new frontend parameters)
    baseline_herd_meal_kg = data.get('baseline_herd_meal_kg', 4.0)
    milking_frequency = data.get('milking_frequency')
    animal_targets = data.get('animal_targets')  # NEW
    lactating_cow_ids = data.get('lactating_cow_ids')  # NEW
    target_mode = data.get('target_mode', 'herd')  # NEW (default to 'herd' for backward compat)

    if target_liters is None:
        return jsonify({"error": "target_liters is required"}), 400

    try:
        # NEW: Support per-cow calculation mode
        if target_mode == 'per_cow' and animal_targets:
            # Calculate based on per-cow targets
            effective_target = sum(t.get('target_liters', 0) for t in animal_targets)
            if effective_target <= 0:
                return jsonify({"error": "animal_targets must contain positive target_liters"}), 400
        else:
            # OLD: Herd-level calculation (backward compatible)
            effective_target = target_liters
        
        schedule = FeedFrequencyHelper.calculate_milking_schedule(
            target_liters=effective_target,
            baseline_herd_meal_kg=baseline_herd_meal_kg,
            milking_frequency=milking_frequency,
        )
        
        return jsonify(schedule), 200
        
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"error": "Failed to calculate schedule", "details": str(exc)}), 500


# Yield Target Management Endpoints
@feed_bp.route('/api/v1/animals/<int:cow_id>/yield-target', methods=['POST'])
@feed_bp.route('/api/animals/<int:cow_id>/yield-target', methods=['POST'])
@jwt_required()
def set_yield_target(cow_id):
    """Set or update yield target for a specific cow."""
    tenant_id = _get_tenant_id_from_claims()
    if not tenant_id:
        return jsonify({"error": "Missing or invalid tenant in token."}), 400

    data = request.get_json() or {}
    target_liters = data.get('target_liters')
    base_herd_feed_kg = data.get('base_herd_feed_kg', 0.0)
    times_to_feed_daily = data.get('times_to_feed_daily', 2)

    if target_liters is None:
        return jsonify({"error": "target_liters is required."}), 400

    try:
        result = YieldTargetService.set_yield_target(
            tenant_id=tenant_id,
            cow_id=cow_id,
            target_liters=target_liters,
            base_herd_feed_kg=base_herd_feed_kg,
            times_to_feed_daily=times_to_feed_daily,
        )
        return jsonify(result), 201 if result.get('action') == 'created' else 200
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"error": "Failed to set yield target.", "details": str(exc)}), 500


@feed_bp.route('/api/v1/animals/<int:cow_id>/yield-target', methods=['GET'])
@feed_bp.route('/api/animals/<int:cow_id>/yield-target', methods=['GET'])
@jwt_required()
def get_yield_target(cow_id):
    """Retrieve yield target for a specific cow."""
    tenant_id = _get_tenant_id_from_claims()
    if not tenant_id:
        return jsonify({"error": "Missing or invalid tenant in token."}), 400

    try:
        target = YieldTargetService.get_yield_target(tenant_id=tenant_id, cow_id=cow_id)
        if not target:
            return jsonify({"error": f"No yield target found for cow {cow_id}."}), 404
        return jsonify(target), 200
    except Exception as exc:
        return jsonify({"error": "Failed to retrieve yield target.", "details": str(exc)}), 500


@feed_bp.route('/api/v1/herd/yield-targets', methods=['GET'])
@feed_bp.route('/api/herd/yield-targets', methods=['GET'])
@jwt_required()
def list_yield_targets():
    """List all active yield targets for the herd."""
    tenant_id = _get_tenant_id_from_claims()
    if not tenant_id:
        return jsonify({"error": "Missing or invalid tenant in token."}), 400

    try:
        targets = YieldTargetService.get_all_yield_targets(tenant_id=tenant_id)
        return jsonify({
            "count": len(targets),
            "targets": targets,
        }), 200
    except Exception as exc:
        return jsonify({"error": "Failed to retrieve yield targets.", "details": str(exc)}), 500


@feed_bp.route('/api/v1/animals/<int:cow_id>/yield-target', methods=['PATCH'])
@feed_bp.route('/api/animals/<int:cow_id>/yield-target', methods=['PATCH'])
@jwt_required()
def update_yield_target(cow_id):
    """Update specific fields of a yield target."""
    tenant_id = _get_tenant_id_from_claims()
    if not tenant_id:
        return jsonify({"error": "Missing or invalid tenant in token."}), 400

    data = request.get_json() or {}

    try:
        result = YieldTargetService.set_yield_target(
            tenant_id=tenant_id,
            cow_id=cow_id,
            target_liters=data.get('target_liters'),
            base_herd_feed_kg=data.get('base_herd_feed_kg', 0.0),
            times_to_feed_daily=data.get('times_to_feed_daily', 2),
        )
        return jsonify(result), 200
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"error": "Failed to update yield target.", "details": str(exc)}), 500


@feed_bp.route('/api/v1/animals/<int:cow_id>/yield-target', methods=['DELETE'])
@feed_bp.route('/api/animals/<int:cow_id>/yield-target', methods=['DELETE'])
@jwt_required()
def deactivate_yield_target(cow_id):
    """Deactivate yield target for a cow."""
    tenant_id = _get_tenant_id_from_claims()
    if not tenant_id:
        return jsonify({"error": "Missing or invalid tenant in token."}), 400

    try:
        result = YieldTargetService.deactivate_yield_target(tenant_id=tenant_id, cow_id=cow_id)
        return jsonify(result), 200
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 404
    except Exception as exc:
        return jsonify({"error": "Failed to deactivate yield target.", "details": str(exc)}), 500


# Herd Feeding Plan Endpoints
@feed_bp.route('/api/v1/herd/feeding-plan/from-targets', methods=['GET'])
@jwt_required()
def calculate_herd_plan_from_targets():
    """Calculate herd feeding plan from saved yield targets (LACTATING cows only)."""
    tenant_id = _get_tenant_id_from_claims()
    if not tenant_id:
        return jsonify({"error": "Missing or invalid tenant in token."}), 400

    milking_frequency = request.args.get('milking_frequency', type=int)

    try:
        plan = HerdFeedingPlanService.calculate_from_cow_targets(
            tenant_id=tenant_id,
            milking_frequency=milking_frequency,
        )
        return jsonify(plan), 200
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"error": "Failed to calculate herd feeding plan.", "details": str(exc)}), 500


@feed_bp.route('/api/v1/herd/feeding-plan/custom', methods=['POST'])
@jwt_required()
def calculate_herd_plan_custom():
    """Calculate herd feeding plan from manually provided cow targets."""
    tenant_id = _get_tenant_id_from_claims()
    if not tenant_id:
        return jsonify({"error": "Missing or invalid tenant in token."}), 400

    data = request.get_json() or {}
    cow_targets = data.get('cow_targets', [])
    baseline_herd_meal_kg = data.get('baseline_herd_meal_kg', 4.0)
    milking_frequency = data.get('milking_frequency')

    try:
        plan = HerdFeedingPlanService.calculate_from_manual_targets(
            cow_targets=cow_targets,
            baseline_herd_meal_kg=baseline_herd_meal_kg,
            milking_frequency=milking_frequency,
        )
        return jsonify(plan), 200
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"error": "Failed to calculate herd feeding plan.", "details": str(exc)}), 500
