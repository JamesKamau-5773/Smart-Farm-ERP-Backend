from app.repositories.supply_repo import MilkRepository
from app.repositories.cow_repo import CowRepository
from flask import jsonify

class ProductionService:
    # Set the anomaly threshold (e.g., a drop > 15% triggers a warning)
    ANOMALY_THRESHOLD_PERCENT = 0.15 

    @staticmethod
    def log_daily_yield(cow_id: int, amount: float, session: str, user_id: int):
        """Processes the milking entry, applies intelligence, and securely logs it."""
        
        # 1. Validate Cow and retrieve current Hardlock state
        cow = CowRepository.get_by_id(cow_id)
        if not cow:
            return jsonify({"error": "Cow not found."}), 404
        
        if not cow.is_active or cow.current_status == 'Dry':
            return jsonify({"error": f"Cow {cow.tag_number} is currently flagged as {cow.current_status} and should not be milked."}), 400

        # 2. Safety First: Inherit the Farmer's Hardlock decision
        # If the cow is locked for medical reasons, this specific milk log is flagged as NOT saleable.
        is_saleable = not cow.is_hardlocked

        # 3. Anomaly Detection (The 7-Day Rolling Average)
        historical_average = MilkRepository.get_cow_average_yield(cow_id, days=7)
        is_anomaly = False
        warning_msg = None

        if historical_average > 0:
            # Did the yield drop significantly below her 7-day average?
            drop_limit = historical_average * (1 - ProductionService.ANOMALY_THRESHOLD_PERCENT)
            if amount < drop_limit:
                is_anomaly = True
                warning_msg = f"Warning: Yield of {amount}L is >15% below her {historical_average:.1f}L average. Health check recommended."

        # 4. Commit the Log
        log = MilkRepository.create_log(
            cow_id=cow_id,
            amount=amount,
            session=session,
            recorded_by=user_id,
            is_saleable=is_saleable,
            is_anomaly=is_anomaly
        )

        # 5. Prepare the Smart Response
        response = {
            "message": "Milk logged successfully.",
            "log_id": log.id,
            "saleable": is_saleable,
            "anomaly_detected": is_anomaly
        }
        
        # Add actionable warnings to the response payload if necessary
        if not is_saleable:
            response["alert_safety"] = "MILK IS ISOLATED. Cow is under medical isolation. Do not mix with commercial batch."
        if warning_msg:
            response["alert_health"] = warning_msg

        return jsonify(response), 201