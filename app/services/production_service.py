from datetime import datetime, timezone
from app.models.supply import MilkLog, MilkSession
from app.repositories.supply_repo import MilkRepository
from app.repositories.cow_repo import CowRepository
from flask import jsonify
from app import db
from app.utils.farm_time import farm_timestamp_for, farm_today, to_farm_date

class ProductionService:
    # Set the anomaly threshold (e.g., a drop > 15% triggers a warning)
    ANOMALY_THRESHOLD_PERCENT = 0.15
    # The drop rule compares a record with the cow's average for the same milking session over
    # this many days before it. Milk lists send the same baseline as ``vs_avg_litres`` (BR-025).
    ANOMALY_WINDOW_DAYS = 7

    @staticmethod
    def evaluate_drop(cow_id: int, amount: float, session: str, tenant_id: int, reference_dt):
        """``(is_drop, average, warning)`` for a record of ``amount`` litres at ``reference_dt``.

        The one milk-drop rule: more than ANOMALY_THRESHOLD_PERCENT below the cow's average for
        the same session over the ANOMALY_WINDOW_DAYS before the record. No average (no earlier
        record of that session in the window) means no verdict, so not a drop.
        """
        average = MilkRepository.get_cow_average_yield(
            cow_id, days=ProductionService.ANOMALY_WINDOW_DAYS, tenant_id=tenant_id,
            as_of=reference_dt, session=session,
        )
        if average <= 0:
            return False, None, None
        if float(amount) >= average * (1 - ProductionService.ANOMALY_THRESHOLD_PERCENT):
            return False, average, None
        percent = round(ProductionService.ANOMALY_THRESHOLD_PERCENT * 100)
        warning = (
            f"Warning: Yield of {float(amount):g}L is >{percent}% below her {average:.1f}L "
            f"{str(session).lower()} average. Health check recommended."
        )
        return True, average, warning

    @staticmethod
    def recheck_drop(log: MilkLog, previous_date, user_id: int | None = None) -> None:
        """Re-apply the drop rule after a record's litres, session or date changed.

        Keeps the flag, the list status and the milk-drop alerts in step with the corrected record:
        a new drop raises an alert; a record that is no longer a drop closes its day's alert if no one
        has started on it and no other record that day is still a drop. Verified records keep their
        status. Does not commit.
        """
        was_drop = bool(log.anomaly_flag)
        is_drop, average, warning = ProductionService.evaluate_drop(
            log.cow_id, float(log.amount_liters), log.session, log.tenant_id, log.timestamp,
        )
        log.anomaly_flag = is_drop
        verified = str(log.status or '').upper() == MilkLog.STATUS_VERIFIED or log.verified_at is not None
        if not verified:
            log.status = MilkLog.STATUS_FLAGGED if is_drop else \
                         MilkLog.STATUS_ISOLATED if not log.is_saleable else \
                         MilkLog.STATUS_RECORDED

        new_date = to_farm_date(log.timestamp)
        moved = previous_date is not None and previous_date != new_date
        db.session.flush()

        if was_drop and previous_date is not None and (not is_drop or moved):
            if not MilkRepository.has_other_flagged_log(log, previous_date):
                for alert in MilkRepository.unreviewed_drop_alerts(log.cow_id, log.tenant_id, previous_date):
                    alert.status = 'RESOLVED'
                    alert.investigation_notes = (
                        'Closed automatically: the milk record was corrected and is no longer a drop.'
                    )
                    alert.investigated_by = int(user_id) if user_id else None
                    alert.investigated_at = datetime.now(timezone.utc)

        if is_drop and (not was_drop or moved):
            if not MilkRepository.has_drop_alert(log.cow_id, log.tenant_id, new_date):
                MilkRepository.create_drop_alert(
                    cow_id=log.cow_id, tenant_id=log.tenant_id, alert_date=new_date,
                    missing_milk_liters=average - float(log.amount_liters), reason=warning, commit=False,
                )

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

        # 3. Anomaly Detection (same session, 7-day average), anchored to the submitted milking date
        # so backdated entries are compared against the average leading up to that date, not today.
        now = datetime.now(timezone.utc)
        reference_dt = farm_timestamp_for(milking_date, now) if milking_date else now
        is_anomaly, historical_average, warning_msg = ProductionService.evaluate_drop(
            livestock_id, amount, session, tenant_id, reference_dt,
        )

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