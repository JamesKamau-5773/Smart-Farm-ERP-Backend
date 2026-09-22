from __future__ import annotations

import json
import logging
from datetime import date, datetime, timezone
from typing import Any, Dict, Optional, Tuple

from flask import jsonify

from app import db
from app.models.enums import CowStatus
from app.models.livestock import AnimalTimelineEvent, BreedingLog, Cow, LactationCycle
from app.repositories.breeding_repo import BreedingLogRepository
from app.repositories.cow_repo import CowRepository
from app.services.genetic_projection_service import GeneticProjectionService

log = logging.getLogger(__name__)


class CalvingService:
    """
    SRP: Owns the complete, atomic domain workflow for logging a birth/calving event.

    Coordinates:
      1. Mother cow validation & master status updates (last_calving_date, status='Lactating', pregnancy_status='Open', due_date=None).
      2. Lactation cycle transition (closing previous cycle, creating a new active cycle).
      3. Breeding log outcome transition (updating pregnant log to 'Calved').
      4. Newborn calf registration in the herd register (if tag/details provided).
      5. Automated genetic score projection for the calf from dam and sire traits.
      6. Timeline event auditing on both mother and calf records.
    """

    @staticmethod
    def normalize_calving_payload(data: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize varying payload conventions (camelCase, snake_case, aliases) from frontend clients."""
        payload = dict(data or {})

        # Date normalization
        calving_date_raw = (
            payload.get("calving_date")
            or payload.get("calvingDate")
            or payload.get("event_date")
            or payload.get("eventDate")
            or payload.get("date")
            or payload.get("timestamp")
        )

        # Calf attributes
        calf_tag = (
            payload.get("calf_tag")
            or payload.get("calfTag")
            or payload.get("calf_tag_number")
            or payload.get("calfTagNumber")
            or payload.get("tag_number")
            or payload.get("tagNumber")
            or payload.get("tag")
        )
        if calf_tag is not None:
            calf_tag = str(calf_tag).strip()
            if not calf_tag:
                calf_tag = None

        calf_name = (
            payload.get("calf_name")
            or payload.get("calfName")
            or payload.get("name")
        )
        if calf_name is not None:
            calf_name = str(calf_name).strip() or None

        calf_sex = (
            payload.get("calf_sex")
            or payload.get("calfSex")
            or payload.get("calf_gender")
            or payload.get("calfGender")
            or payload.get("gender")
            or payload.get("sex")
        )
        if calf_sex is not None:
            calf_sex = str(calf_sex).strip().capitalize() or None

        # Birth weight
        birth_weight_raw = (
            payload.get("birth_weight")
            or payload.get("birthWeight")
            or payload.get("birth_weight_kg")
            or payload.get("birthWeightKg")
            or payload.get("weight")
        )
        birth_weight = None
        if birth_weight_raw not in (None, ""):
            try:
                birth_weight = round(float(birth_weight_raw), 2)
            except (ValueError, TypeError):
                birth_weight = None

        # Delivery outcome & ease
        delivery_outcome = (
            payload.get("delivery_outcome")
            or payload.get("deliveryOutcome")
            or payload.get("outcome")
        )
        # Accept boolean-style live/stillborn flags as an alternative to the outcome string
        if not delivery_outcome:
            is_stillborn_flag = payload.get("is_stillborn")
            if is_stillborn_flag is None:
                is_stillborn_flag = payload.get("isStillborn")
            is_live_flag = payload.get("is_live_birth")
            if is_live_flag is None:
                is_live_flag = payload.get("isLiveBirth")
            if is_stillborn_flag is not None:
                delivery_outcome = "Stillborn" if bool(is_stillborn_flag) else "Live Birth"
            elif is_live_flag is not None:
                delivery_outcome = "Live Birth" if bool(is_live_flag) else "Stillborn"
        delivery_outcome = delivery_outcome or "Live Birth"
        if delivery_outcome:
            delivery_outcome = str(delivery_outcome).strip()

        calving_ease = (
            payload.get("calving_ease")
            or payload.get("calvingEase")
            or payload.get("ease")
            or "Normal"
        )
        if calving_ease:
            calving_ease = str(calving_ease).strip()

        notes = (
            payload.get("notes")
            or payload.get("description")
            or payload.get("remarks")
            or ""
        )
        if notes:
            notes = str(notes).strip() or None

        breed_status = (
            payload.get("breed_status")
            or payload.get("breedStatus")
            or payload.get("breed")
        )

        create_calf = payload.get("create_calf")
        if create_calf is None:
            create_calf = payload.get("createCalf")
        if create_calf is None:
            # Infer: if calf_tag is provided and delivery outcome is not stillborn, default to True
            is_stillborn = bool(delivery_outcome and "still" in delivery_outcome.lower())
            create_calf = bool(calf_tag and not is_stillborn)

        return {
            "calving_date_raw": calving_date_raw,
            "calf_tag": calf_tag,
            "calf_name": calf_name,
            "calf_sex": calf_sex,
            "birth_weight": birth_weight,
            "delivery_outcome": delivery_outcome,
            "calving_ease": calving_ease,
            "notes": notes,
            "breed_status": breed_status,
            "create_calf": bool(create_calf),
            "sire_pta_scores": payload.get("sire_pta_scores") or payload.get("sirePTAScores"),
        }

    @staticmethod
    def _parse_calving_date(raw_date: Any) -> Tuple[Optional[date], Optional[datetime], Optional[str]]:
        if not raw_date:
            now_dt = datetime.now(timezone.utc)
            return now_dt.date(), now_dt, None

        if isinstance(raw_date, datetime):
            dt = raw_date if raw_date.tzinfo is not None else raw_date.replace(tzinfo=timezone.utc)
            return dt.date(), dt, None

        if isinstance(raw_date, date):
            dt = datetime.combine(raw_date, datetime.min.time(), tzinfo=timezone.utc)
            return raw_date, dt, None

        raw_str = str(raw_date).strip()
        try:
            if "T" in raw_str:
                dt = datetime.fromisoformat(raw_str.replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                d = dt.date()
            else:
                d = datetime.strptime(raw_str, "%Y-%m-%d").date()
                dt = datetime.combine(d, datetime.min.time(), tzinfo=timezone.utc)

            if d > date.today():
                return None, None, "Calving date cannot be in the future."
            return d, dt, None
        except (ValueError, TypeError):
            return None, None, "calving_date must be a valid ISO date or YYYY-MM-DD format."

    @staticmethod
    def record_calving(
        *,
        tenant_id: int,
        cow_id_or_tag: str | int,
        data: Dict[str, Any],
        user_id: Optional[int] = None,
    ) -> Tuple[Dict[str, Any], int]:
        """
        Executes the atomic calving/birth workflow:
          1. Updates dam record (status=Lactating, last_calving_date, pregnancy_status='Open', due_date=None)
          2. Closes old lactation cycle and creates new active LactationCycle
          3. Marks breeding log as 'Calved'
          4. Registers calf in herd if tag provided
          5. Projects calf genetic scores if sire PTA data is available
          6. Records timeline events for dam and calf
        """
        if tenant_id is None:
            return {"error": "Missing or invalid tenant in token."}, 400

        # Resolve mother cow (dam)
        cow = None
        try:
            cow_id_int = int(cow_id_or_tag)
            cow = CowRepository.get_by_id(cow_id_int, tenant_id=tenant_id)
        except (TypeError, ValueError):
            pass

        if not cow:
            cow = CowRepository.get_by_tag(str(cow_id_or_tag), tenant_id=tenant_id)

        if not cow:
            return {"error": f"Cow '{cow_id_or_tag}' not found for this tenant."}, 404

        if not cow.is_active:
            return {"error": "Cannot log calving for an inactive/archived cow."}, 400

        # Normalize and validate payload
        norm = CalvingService.normalize_calving_payload(data)
        calving_d, calving_dt, date_err = CalvingService._parse_calving_date(norm["calving_date_raw"])
        if date_err:
            return {"error": date_err}, 400

        # Validate calf tag uniqueness if calf registration is requested
        calf_tag = norm["calf_tag"]
        if norm["create_calf"] and calf_tag:
            existing_active_calf = Cow.query.filter_by(
                tenant_id=tenant_id, tag_number=calf_tag, is_active=True
            ).first()
            if existing_active_calf:
                return {
                    "error": f"An active animal with tag number '{calf_tag}' already exists for this tenant."
                }, 409

        try:
            # 1. Update mother cow master record
            cow.last_calving_date = calving_d
            cow.status = CowStatus.LACTATING
            cow.pregnancy_status = "Open"
            cow.due_date = None
            db.session.add(cow)

            # 2. Lactation Cycle management
            existing_cycles = LactationCycle.query.filter_by(cow_id=cow.id).all()
            for cycle in existing_cycles:
                cycle.is_active = False
                db.session.add(cycle)

            new_cycle = LactationCycle(
                cow_id=cow.id,
                cycle_number=len(existing_cycles) + 1,
                actual_calving_date=calving_d,
                is_active=True,
            )
            db.session.add(new_cycle)

            # 3. Update Breeding Log outcome to 'Calved'
            breeding_log = (
                BreedingLog.query.filter(
                    BreedingLog.cow_id == cow.id,
                    BreedingLog.tenant_id == tenant_id,
                    BreedingLog.status.in_(["Pregnant", "Pending"]),
                )
                .order_by(BreedingLog.insemination_date.desc(), BreedingLog.id.desc())
                .first()
            )

            sire_name = cow.sire_name
            sire_pta_scores = norm.get("sire_pta_scores")

            if breeding_log:
                breeding_log.status = "Calved"
                db.session.add(breeding_log)

                if not sire_pta_scores and breeding_log.sire_pta_scores:
                    sire_pta_scores = breeding_log.sire_pta_scores

                # Extract sire name & PTA traits from breeding log if available
                if breeding_log.semen:
                    sire_name = breeding_log.semen.bull_name
                    if not sire_pta_scores and breeding_log.semen.traits_to_improve:
                        sire_raw = breeding_log.semen.traits_to_improve
                        if isinstance(sire_raw, str):
                            try:
                                sire_pta_scores = json.loads(sire_raw)
                            except (json.JSONDecodeError, TypeError):
                                sire_pta_scores = {}
                        elif isinstance(sire_raw, dict):
                            sire_pta_scores = sire_raw
                elif breeding_log.external_sire_code:
                    sire_name = breeding_log.external_sire_code

            # 4. Register Calf in Herd if requested
            calf = None
            if norm["create_calf"] and calf_tag:
                calf_breed_status = norm["breed_status"] or cow.breed_status or "Foundation"
                calf = Cow(
                    tenant_id=tenant_id,
                    tag_number=calf_tag,
                    name=norm["calf_name"],
                    date_of_birth=calving_d,
                    breed_status=calf_breed_status,
                    dam_id=cow.id,
                    sire_name=sire_name,
                    status=CowStatus.CALF,
                    pregnancy_status="Not Applicable",
                    is_active=True,
                    birth_weight_kg=norm["birth_weight"],
                )
                db.session.add(calf)
                db.session.flush()  # Flush to get calf.id

                # 4b. Auto-project genetic scores for calf
                if sire_pta_scores and isinstance(sire_pta_scores, dict):
                    try:
                        GeneticProjectionService.project_calf_scores(
                            calf_cow_id=calf.id,
                            dam_cow_id=cow.id,
                            sire_pta_scores=sire_pta_scores,
                            tenant_id=tenant_id,
                        )
                        log.info("Auto-projected genetic scores for newborn calf %s (id=%s)", calf_tag, calf.id)
                    except Exception as gen_err:
                        log.warning("Could not project genetic scores for calf %s: %s", calf.id, str(gen_err))

                # 4c. Record birth timeline event on calf
                calf_timeline_event = AnimalTimelineEvent(
                    tenant_id=tenant_id,
                    cow_id=calf.id,
                    event_type="birth",
                    title="Born / Registered",
                    description=f"Born to dam {cow.tag_number} ({cow.name or 'Unnamed'}). Delivery: {norm['delivery_outcome']}.",
                    event_date=calving_dt,
                    event_data={
                        "dam_id": cow.id,
                        "dam_tag": cow.tag_number,
                        "dam_name": cow.name,
                        "birth_weight_kg": norm["birth_weight"],
                        "delivery_outcome": norm["delivery_outcome"],
                        "calving_ease": norm["calving_ease"],
                        "gender": norm["calf_sex"],
                        "sire_name": sire_name,
                    },
                    created_by=user_id,
                )
                db.session.add(calf_timeline_event)

            # 5. Record Calving Timeline Event on Dam
            event_title = f"Calved - {norm['calf_sex'] or 'Calf'}"
            if norm["delivery_outcome"] and "still" in norm["delivery_outcome"].lower():
                event_title = f"Calved - {norm['delivery_outcome']}"

            dam_timeline_event = AnimalTimelineEvent(
                tenant_id=tenant_id,
                cow_id=cow.id,
                event_type="calving",
                title=event_title,
                description=norm["notes"] or f"Delivery outcome: {norm['delivery_outcome']}. Calving ease: {norm['calving_ease']}.",
                event_date=calving_dt,
                event_data={
                    "calf_id": calf.id if calf else None,
                    "calf_tag": calf_tag if calf else None,
                    "calf_name": norm["calf_name"],
                    "calf_sex": norm["calf_sex"],
                    "calf_gender": norm["calf_sex"],
                    "birth_weight_kg": norm["birth_weight"],
                    "birth_weight": norm["birth_weight"],
                    "delivery_outcome": norm["delivery_outcome"],
                    "calving_ease": norm["calving_ease"],
                    "breeding_log_id": breeding_log.id if breeding_log else None,
                    "notes": norm["notes"],
                },
                created_by=user_id,
            )
            db.session.add(dam_timeline_event)

            db.session.commit()

            response_data = {
                "message": "Calving event and birth recorded successfully.",
                "event": {
                    "id": dam_timeline_event.id,
                    "cow_id": cow.id,
                    "event_type": dam_timeline_event.event_type,
                    "title": dam_timeline_event.title,
                    "description": dam_timeline_event.description,
                    "event_date": dam_timeline_event.event_date.isoformat(),
                    "event_data": dam_timeline_event.event_data,
                    "created_at": dam_timeline_event.created_at.isoformat() if dam_timeline_event.created_at else None,
                },
                "mother": {
                    "id": cow.id,
                    "tag_number": cow.tag_number,
                    "name": cow.name,
                    "status": cow.status,
                    "current_status": CowStatus.LACTATING,
                    "pregnancy_status": cow.pregnancy_status,
                    "last_calving_date": cow.last_calving_date.isoformat() if cow.last_calving_date else None,
                    "last_calved": cow.last_calving_date.isoformat() if cow.last_calving_date else None,
                    "due_date": None,
                },
                "calf": (
                    {
                        "id": calf.id,
                        "tag_number": calf.tag_number,
                        "name": calf.name,
                        "date_of_birth": calf.date_of_birth.isoformat(),
                        "breed_status": calf.breed_status,
                        "dam_id": cow.id,
                        "status": calf.status,
                        "current_status": CowStatus.CALF,
                        "birth_weight_kg": float(calf.birth_weight_kg) if calf.birth_weight_kg is not None else None,
                    }
                    if calf
                    else None
                ),
                "breeding_log": (
                    {
                        "id": breeding_log.id,
                        "status": breeding_log.status,
                    }
                    if breeding_log
                    else None
                ),
                "lactation_cycle": {
                    "id": new_cycle.id,
                    "cycle_number": new_cycle.cycle_number,
                    "actual_calving_date": new_cycle.actual_calving_date.isoformat(),
                    "is_active": new_cycle.is_active,
                },
            }
            return response_data, 201

        except Exception as exc:
            db.session.rollback()
            log.exception("Failed to record calving for cow_id=%s: %s", cow.id, str(exc))
            return {"error": f"Failed to record calving event: {str(exc)}"}, 500
