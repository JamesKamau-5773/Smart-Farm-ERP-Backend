from flask import Blueprint, request, jsonify
from app.services.feed_frequency_helper import FeedFrequencyHelper

feed_bp = Blueprint('feed', __name__)


@feed_bp.route('/api/v1/feed/calculate-schedule', methods=['POST'])
def calculate_schedule():
    data = request.get_json() or {}
    target_liters = data.get('target_liters')
    baseline_herd_meal_kg = data.get('baseline_herd_meal_kg', 4.0)
    milking_frequency = data.get('milking_frequency')

    if target_liters is None:
        return jsonify({"error": "target_liters is required"}), 400

    try:
        schedule = FeedFrequencyHelper.calculate_milking_schedule(
            target_liters=target_liters,
            baseline_herd_meal_kg=baseline_herd_meal_kg,
            milking_frequency=milking_frequency,
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"error": "Failed to calculate schedule", "details": str(exc)}), 500

    return jsonify(schedule), 200
