from datetime import datetime, timezone
from app.models.supply import MilkLog, MilkSession
from app.repositories.supply_repo import MilkRepository
from app.repositories.cow_repo import CowRepository
from flask import jsonify
from app.utils.farm_time import farm_timestamp_for, farm_today, to_farm_date

class ProductionService:
    # Set the anomaly threshold (e.g., a drop > 15% triggers a warning)
    ANOMALY_THRESHOLD_PERCENT = 0.15
    # The drop rule compares a record with the cow's average over this many days before it,
    # across all sessions. Milk lists send the same baseline as ``vs_avg_litres`` (BR-025).
    ANOMALY_WINDOW_DAYS = 7

    @staticmethod
    def log_daily_yield(cow_id: int, amount: float, session: str, user_id: int, tenant_id: int, milking_date=None,
                        source: str = MilkLog.SOURCE_APP, milker_employee_id: int | None = None):
        """Processes the milking entry, applies intelligence, and securely logs it."""
        livestock_id = cow_id

        # Sessions are stored and returned as Morning / Midday / Evening only.
        canonical_session = MilkSession.normalize(session)
        if canonical_session is None:
            return jsonify({
                "code": "VALIDATION_ERROR",
                "error": "session must be Morning, Midday or Evening.",
                "fields": {"session": "invalid"},
            }), 400
        session = canonical_session
        
        # 1. Validate Livestock and retrieve current Hardlock state
        livestock = CowRepository.get_by_id(livestock_id, tenant_id=tenant_id)
        if not livestock:
            return jsonify({"error": "Cow not found."}), 404
        
        if not livestock.is_active or livestock.current_status == 'Dry':
            return jsonify({"error": f"Livestock {livestock.tag_number} is currently flagged as {livestock.current_status} and should not be milked."}), 400

        # 1b. One record per cow, milking session and day. Retries of the same submission are
        # replayed by the idempotency middleware before reaching here, so this only stops a
        # genuine second entry (e.g. two people recording the same milking).
        target_date = milking_date or farm_today()
        existing = MilkRepository.find_session_log(livestock_id, session, target_date, tenant_id)
        if existing:
            cow_label = livestock.name or livestock.tag_number
            return jsonify({
                "error": (
                    f"{cow_label}'s {str(session).strip().lower()} milk for {target_date.isoformat()} is already recorded "
                    f"({float(existing.amount_liters):g} L). Edit that record instead of adding another."
                ),
                "code": "DUPLICATE_MILK_ENTRY",
                "existing_log_id": existing.id,
            }), 409

        # 2. Safety First: Inherit the Farmer's Hardlock decision
        # If the livestock is locked for medical reasons, this specific milk log is flagged as NOT saleable.
        is_saleable = not livestock.is_hardlocked

        # 3. Anomaly Detection (The 7-Day Rolling Average), anchored to the submitted milking date
        # so backdated entries are compared against the average leading up to that date, not today.
        now = datetime.now(timezone.utc)
        reference_dt = farm_timestamp_for(milking_date, now) if milking_date else now
        historical_average = MilkRepository.get_cow_average_yield(livestock_id, days=ProductionService.ANOMALY_WINDOW_DAYS, tenant_id=tenant_id, as_of=reference_dt)
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
            cow_id=livestock_id,
            amount=amount,
            session=session,
            recorded_by=user_id,
            tenant_id=tenant_id,
            is_saleable=is_saleable,
            is_anomaly=is_anomaly,
            milking_date=milking_date,
            source=source,
            milker_employee_id=milker_employee_id,
        )

        # 4b. Raise a manager-review alert so the drop actually surfaces in the review queue.
        if is_anomaly:
            MilkRepository.create_drop_alert(
                cow_id=livestock_id,
                tenant_id=tenant_id,
                alert_date=to_farm_date(log.timestamp),
                missing_milk_liters=historical_average - amount,
                reason=warning_msg
            )

        # 5. Prepare the Smart Response
        response = {
            "message": "Milk logged successfully.",
            "id": log.id,
            "log_id": log.id,
            "cow_id": log.cow_id,
            "cow_name": livestock.name,
            "amount": float(log.amount_liters),
            "session": log.session,
            "milkingDate": to_farm_date(log.timestamp).isoformat() if log.timestamp else None,
            "status": log.status,
            "saleable": is_saleable,
            "anomaly_detected": is_anomaly,
            "recorded_by": log.recorded_by,
            "recorded_via": log.source,
            "milker_id": log.milker_employee_id,
        }
        
        # Add actionable warnings to the response payload if necessary
        if not is_saleable:
            response["alert_safety"] = "MILK IS ISOLATED. Livestock is under medical isolation. Do not mix with commercial batch."
        if warning_msg:
            response["alert_health"] = warning_msg

        return jsonify(response), 201