from decimal import Decimal, InvalidOperation


class FeedFrequencyHelper:
    """Helpers for computing feeding schedules for milking herds.

    Behavior:
    - Validates numeric inputs and non-negative targets.
    - Determines a `recommended_frequency` from computed total meal need
      but honors an explicit `milking_frequency` override if provided.
    - Uses simple arithmetic; callers may round or present results.
    """

    @staticmethod
    def calculate_milking_schedule(target_liters, baseline_herd_meal_kg=4.0, milking_frequency=None):
        # Validate and coerce inputs
        try:
            target_liters = float(target_liters)
        except (TypeError, ValueError):
            raise ValueError("target_liters must be a numeric value")

        if target_liters < 0:
            raise ValueError("target_liters must be non-negative")

        try:
            baseline_herd_meal_kg = float(baseline_herd_meal_kg)
        except (TypeError, ValueError):
            raise ValueError("baseline_herd_meal_kg must be numeric")

        # Compute needs
        total_meal_needed_kg = max(0.0, (target_liters - 10.0) / 1.5)
        milking_topup_total_kg = max(0.0, total_meal_needed_kg - baseline_herd_meal_kg)

        # Decide recommended frequency based on load
        if total_meal_needed_kg > 8.0:
            recommended_frequency = 4
            reason = "High grain load. Split into 4 feedings to prevent rumen acidosis."
        elif total_meal_needed_kg > 5.0:
            recommended_frequency = 3
            reason = "Moderate grain load. Split 3 times daily to optimize absorption."
        else:
            recommended_frequency = 2
            reason = "Standard layout. 2 daily feedings."

        # Honor explicit override if provided; otherwise use recommended
        if milking_frequency is None:
            milking_frequency = recommended_frequency
        else:
            try:
                milking_frequency = int(milking_frequency)
            except (TypeError, ValueError):
                raise ValueError("milking_frequency must be an integer if provided")
            if milking_frequency <= 0:
                raise ValueError("milking_frequency must be greater than 0")

        # Guard against zero-division (shouldn't happen after validation)
        per_session_kg = milking_topup_total_kg / float(milking_frequency) if milking_frequency else 0.0

        return {
            "target_liters": float(target_liters),
            "total_dairy_meal_kg": round(total_meal_needed_kg, 2),
            "base_herd_mix_kg": float(baseline_herd_meal_kg),
            "extra_milking_topup_total_kg": round(milking_topup_total_kg, 2),
            "per_milking_session_kg": round(per_session_kg, 2),
            "suggested_yard_feedings": int(recommended_frequency),
            "used_milking_frequency": int(milking_frequency),
            "farmer_reasoning": reason,
        }
