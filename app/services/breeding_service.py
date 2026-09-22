from __future__ import annotations

import math
import os
from datetime import date, datetime, timezone
from decimal import Decimal

from flask import current_app, jsonify
from werkzeug.utils import secure_filename
from app.utils.uploads import validate_certificate_upload

from app.repositories.breeding_repo import (
    BreedingAnalyticsRepository,
    BreedingLogRepository,
    HeatObservationRepository,
    SemenInventoryRepository,
)
from app.repositories.cow_repo import CowRepository
from app import db
from app.models.livestock import CowStatus, HeatObservation
from app.services.animal_timeline_service import AnimalTimelineService
from app.services.reproduction_service import ReproductionService
from app.tasks.breeding_tasks import schedule_pregnancy_check_reminder


class BreedingService:
    VALID_STATUSES = {"Pending", "Pregnant", "Failed", "Calved"}
    VALID_SEMEN_PROVIDERS = {"FARM", "VET"}
    # UI-facing labels that map onto a canonical BreedingLog.status value.
    # "Open"/"Not Pregnant" describe the cow's resulting pregnancy_status, not
    # the breeding attempt's own outcome, but a failed insemination is exactly
    # what puts her back to Open, so both aliases resolve to "Failed".
    STATUS_ALIASES = {
        "OPEN": "Failed",
        "NOT PREGNANT": "Failed",
    }

    @staticmethod
    def _normalize_status_input(raw: str) -> str:
        cleaned = (raw or "").strip()
        alias = BreedingService.STATUS_ALIASES.get(cleaned.upper())
        return alias or cleaned.title()

    @staticmethod
    def _normalize_provider(value):
        normalized = str(value or "").strip().upper()
        alias_map = {
            "FARM": "FARM",
            "FARM_INVENTORY": "FARM",
            "INVENTORY": "FARM",
            "VET": "VET",
            "VET_PROVIDED": "VET",
            "EXTERNAL": "VET",
            "EXTERNAL_VET": "VET",
        }
        return alias_map.get(normalized, normalized)

    @staticmethod
    def _to_float(value):
        if isinstance(value, Decimal):
            return float(value)
        return value

    @staticmethod
    def _parse_int(value):
        if isinstance(value, bool):
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _resolve_cow(tenant_id: int, cow_identifier):
        cow_identifier_value = str(cow_identifier).strip() if cow_identifier is not None else ""
        livestock_id = BreedingService._parse_int(cow_identifier)
        if livestock_id is not None:
            livestock = CowRepository.get_by_id(livestock_id, tenant_id=tenant_id)
            if livestock:
                return livestock

        if cow_identifier_value:
            livestock = CowRepository.get_by_tag(cow_identifier_value, tenant_id=tenant_id)
            if livestock:
                return livestock
            livestock = CowRepository.get_by_name(cow_identifier_value, tenant_id=tenant_id)
            if livestock:
                return livestock

        return None

    @staticmethod
    def _resolve_semen(tenant_id: int, semen_identifier, provided_by: str):
        if provided_by == "VET":
            return None

        semen_identifier_value = str(semen_identifier).strip() if semen_identifier is not None else ""
        if not semen_identifier_value:
            return None

        semen_id = BreedingService._parse_int(semen_identifier)
        if semen_id is not None:
            semen = SemenInventoryRepository.get_by_id_for_tenant(semen_id, tenant_id)
            if semen:
                return semen

        semen = SemenInventoryRepository.get_by_straw_code_for_tenant(semen_identifier_value, tenant_id)
        if semen:
            return semen

        semen = SemenInventoryRepository.get_by_bull_name_for_tenant(semen_identifier_value, tenant_id)
        return semen

    @staticmethod
    def _extract_insemination_time(data: dict):
        for key in ("insemination_time", "inseminationTime", "ai_time", "aiTime"):
            raw_value = data.get(key)
            if raw_value is None or raw_value == "":
                continue
            try:
                from datetime import time
                if isinstance(raw_value, str):
                    return time.fromisoformat(raw_value)
                return raw_value
            except ValueError:
                return None
        return None

    @staticmethod
    def _parse_service_fee(value):
        if value in (None, ""):
            return None
        try:
            fee = float(value)
            if fee < 0:
                raise ValueError
            return fee
        except (TypeError, ValueError):
            raise ValueError("service_fee must be a non-negative number.")

    @staticmethod
    def _parse_sire_pta_scores(value):
        if value in (None, ""):
            return None
        if not isinstance(value, dict) or not value:
            raise ValueError("sire_pta_scores must be a non-empty object mapping trait names to numbers.")

        scores = {}
        for raw_name, raw_value in value.items():
            trait_name = str(raw_name).strip()
            if not trait_name:
                raise ValueError("sire_pta_scores contains an empty trait name.")
            try:
                score = float(raw_value)
            except (TypeError, ValueError):
                raise ValueError(f"Invalid PTA value for trait '{trait_name}'.")
            if not math.isfinite(score):
                raise ValueError(f"Invalid PTA value for trait '{trait_name}'.")
            scores[trait_name] = score
        return scores

    @staticmethod
    def _build_insemination_payload(log, milestones):
        return {
            "message": "Insemination logged successfully.",
            "breeding_log_id": log.id,
            "provided_by": log.provided_by,
            "semen_source_label": "Farm Inventory" if log.provided_by == "FARM" else "Vet Provided",
            "inventory_semen_id": log.inventory_semen_id,
            "external_sire_code": log.external_sire_code,
            "sire_pta_scores": log.sire_pta_scores,
            "semen_id": log.inventory_semen_id,
            "expected_calving_date": milestones["expected_calving_date"].isoformat(),
            "pregnancy_check_date": milestones["pregnancy_check_date"].isoformat(),
            "certificate_number": log.certificate_number,
            "technician_name": log.technician_name,
            "service_fee": float(log.service_fee) if log.service_fee is not None else None,
            "owner_name": log.owner_name,
            "farm_location": log.farm_location,
            "insemination_time": log.insemination_time.isoformat() if log.insemination_time else None,
            "certificate_image_url": log.certificate_image_url,
            "heat_observation_id": log.heat_observation.id if log.heat_observation else None,
        }

    @staticmethod
    def _serialize_heat_observation(observation):
        return {
            "id": observation.id,
            "cow_id": observation.cow_id,
            "observed_at": observation.observed_at.isoformat(),
            "intensity": observation.intensity,
            "signs": observation.signs or [],
            "notes": observation.notes,
            "next_window_start": observation.next_window_start.isoformat(),
            "next_window_end": observation.next_window_end.isoformat(),
            "breeding_log_id": observation.breeding_log_id,
            "created_by": observation.created_by,
        }

    @staticmethod
    def record_heat_observation(tenant_id: int, user_id: int | None, data: dict):
        livestock = BreedingService._resolve_cow(tenant_id, data.get("cow_id", data.get("cowId")))
        if not livestock:
            return jsonify({"error": "Cow not found for this tenant."}), 404

        observed_at_raw = data.get("observed_at", data.get("observedAt"))
        if not observed_at_raw:
            return jsonify({"error": "observed_at is required."}), 400
        try:
            observed_at = datetime.fromisoformat(str(observed_at_raw).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return jsonify({"error": "observed_at must be a valid ISO date-time."}), 400
        if observed_at.tzinfo is None:
            observed_at = observed_at.replace(tzinfo=timezone.utc)

        intensity = str(data.get("intensity") or "MEDIUM").strip().upper()
        if intensity not in {"LOW", "MEDIUM", "HIGH"}:
            return jsonify({"error": "intensity must be LOW, MEDIUM, or HIGH."}), 400
        signs = data.get("signs") or []
        if not isinstance(signs, list) or any(not isinstance(sign, str) or not sign.strip() for sign in signs):
            return jsonify({"error": "signs must be a list of non-empty strings."}), 400
        signs = list(dict.fromkeys(sign.strip() for sign in signs))

        window_start, window_end = ReproductionService.get_next_heat_window(observed_at.date())
        observation = HeatObservation(
            tenant_id=tenant_id,
            cow_id=livestock.id,
            observed_at=observed_at,
            intensity=intensity,
            signs=signs,
            notes=(data.get("notes") or "").strip() or None,
            next_window_start=window_start,
            next_window_end=window_end,
            created_by=user_id,
        )
        db.session.add(observation)
        db.session.commit()

        AnimalTimelineService.record_event(
            tenant_id=tenant_id,
            cow_id=livestock.id,
            event_type="heat_observation",
            title=f"Heat observed ({intensity.lower()})",
            description=observation.notes,
            event_date=observed_at,
            event_data={
                "heat_observation_id": observation.id,
                "signs": signs,
                "next_window_start": window_start.isoformat(),
                "next_window_end": window_end.isoformat(),
            },
            created_by=user_id,
        )
        return jsonify(BreedingService._serialize_heat_observation(observation)), 201

    @staticmethod
    def list_heat_observations(tenant_id: int, cow_identifier=None):
        cow_id = None
        if cow_identifier not in (None, ""):
            livestock = BreedingService._resolve_cow(tenant_id, cow_identifier)
            if not livestock:
                return jsonify({"error": "Cow not found for this tenant."}), 404
            cow_id = livestock.id
        rows = HeatObservationRepository.list_by_tenant(tenant_id, cow_id=cow_id)
        return jsonify({"items": [BreedingService._serialize_heat_observation(row) for row in rows]}), 200

    @staticmethod
    def attach_certificate_image(tenant_id: int, log_id: int, file_storage):
        if file_storage is None:
            return jsonify({"error": "No certificate file was provided."}), 400

        if not getattr(file_storage, 'filename', None):
            return jsonify({"error": "Invalid certificate file."}), 400

        log = BreedingLogRepository.get_by_id_for_tenant(log_id, tenant_id)
        if not log:
            return jsonify({"error": "Breeding log not found for this tenant."}), 404

        filename = secure_filename(file_storage.filename)
        if not filename:
            return jsonify({"error": "File name is invalid."}), 400
        try:
            validate_certificate_upload(file_storage)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

        upload_dir = os.path.join(current_app.config['UPLOAD_ROOT'], 'ai_certificates', f'tenant_{tenant_id}')
        os.makedirs(upload_dir, exist_ok=True)

        file_path = os.path.join(upload_dir, f"{log.id}_{filename}")
        file_storage.save(file_path)

        log.certificate_image_url = f"/uploads/ai_certificates/tenant_{tenant_id}/{os.path.basename(file_path)}"
        db.session.commit()

        return jsonify({
            "message": "AI certificate uploaded successfully.",
            "breeding_log_id": log.id,
            "certificate_image_url": log.certificate_image_url,
        }), 200

    @staticmethod
    def add_semen_inventory(tenant_id: int, data: dict):
        bull_name = (data.get("bull_name") or "").strip()
        straw_code = (data.get("straw_code") or "").strip()
        breed = (data.get("breed") or "").strip()

        if not bull_name or not straw_code or not breed:
            return jsonify({"error": "bull_name, straw_code, and breed are required."}), 400

        existing = SemenInventoryRepository.get_by_straw_code_for_tenant(straw_code, tenant_id)
        if existing:
            return jsonify({"error": "straw_code already exists for this tenant."}), 409

        stock_level = data.get("stock_level", 0)
        try:
            stock_level = int(stock_level)
            if stock_level < 0:
                return jsonify({"error": "stock_level cannot be negative."}), 400
        except (TypeError, ValueError):
            return jsonify({"error": "stock_level must be an integer."}), 400

        item = SemenInventoryRepository.create(
            tenant_id=tenant_id,
            bull_name=bull_name,
            straw_code=straw_code,
            breed=breed,
            provider=data.get("provider"),
            cost=data.get("cost"),
            stock_level=stock_level,
            traits_to_improve=data.get("traits_to_improve"),
        )

        return jsonify(
            {
                "message": "Semen inventory item created.",
                "id": item.id,
                "bull_name": item.bull_name,
                "straw_code": item.straw_code,
                "stock_level": item.stock_level,
            }
        ), 201

    @staticmethod
    def list_semen_inventory(tenant_id: int):
        items = SemenInventoryRepository.list_by_tenant(tenant_id)
        payload = [
            {
                "id": item.id,
                "bull_name": item.bull_name,
                "straw_code": item.straw_code,
                "breed": item.breed,
                "provider": item.provider,
                "cost": BreedingService._to_float(item.cost),
                "stock_level": item.stock_level,
                "traits_to_improve": item.traits_to_improve or [],
            }
            for item in items
        ]
        return jsonify(payload), 200

    @staticmethod
    def log_insemination(tenant_id: int, data: dict):
        cow_identifier = data.get("cow_id", data.get("cowId"))
        semen_identifier = data.get("semen_id", data.get("semenId"))
        if not semen_identifier:
            semen_identifier = data.get("semen_code", data.get("semenCode"))
        external_sire_code = data.get("external_sire_code", data.get("externalSireCode"))
        if not external_sire_code:
            external_sire_code = data.get("sireCode", data.get("sire_code"))
        provided_by_raw = data.get("provided_by", data.get("providedBy"))
        if not provided_by_raw:
            provided_by_raw = data.get("semen_source", data.get("semenSource", "FARM"))
        provided_by = BreedingService._normalize_provider(provided_by_raw)
        sire_pta_scores_raw = data.get("sire_pta_scores", data.get("sirePTAScores"))
        insemination_date_raw = data.get("insemination_date", data.get("inseminationDate"))
        if not insemination_date_raw:
            insemination_date_raw = data.get("aiDate", data.get("ai_date"))

        if provided_by not in BreedingService.VALID_SEMEN_PROVIDERS:
            return jsonify({"error": "provided_by must be FARM or VET."}), 400

        if not cow_identifier or not insemination_date_raw:
            return jsonify({"error": "cow_id and insemination_date are required."}), 400

        if provided_by == "FARM" and not semen_identifier:
            return jsonify({"error": "semen_id is required when provided_by is FARM."}), 400

        try:
            insemination_date = date.fromisoformat(str(insemination_date_raw))
        except (ValueError, TypeError):
            return jsonify({"error": "Invalid insemination_date format (YYYY-MM-DD)."}), 400

        livestock = BreedingService._resolve_cow(tenant_id, cow_identifier)
        if not livestock:
            return jsonify({"error": "Cow not found."}), 404

        heat_observation = None
        heat_observation_id = data.get("heat_observation_id", data.get("heatObservationId"))
        if heat_observation_id not in (None, ""):
            parsed_observation_id = BreedingService._parse_int(heat_observation_id)
            heat_observation = HeatObservationRepository.get_by_id_for_tenant(parsed_observation_id, tenant_id)
            if not heat_observation:
                return jsonify({"error": "Heat observation not found for this tenant."}), 404
            if heat_observation.cow_id != livestock.id:
                return jsonify({"error": "Heat observation belongs to a different cow."}), 400
            if heat_observation.breeding_log_id is not None:
                return jsonify({"error": "Heat observation is already linked to an insemination."}), 409

        semen = BreedingService._resolve_semen(tenant_id, semen_identifier, provided_by)
        resolved_external_sire_code = None
        stock_level_remaining = None

        if provided_by == "FARM":
            if not semen:
                return jsonify({"error": "Semen inventory item not found for this tenant."}), 404
            if semen.stock_level > 0:
                semen.stock_level -= 1
            stock_level_remaining = semen.stock_level
            if sire_pta_scores_raw in (None, "") and isinstance(semen.traits_to_improve, dict):
                sire_pta_scores_raw = semen.traits_to_improve
        else:
            resolved_external_sire_code = str(external_sire_code or semen_identifier or "").strip()
            if not resolved_external_sire_code:
                return jsonify({"error": "external_sire_code is required when provided_by is VET."}), 400

        try:
            sire_pta_scores = BreedingService._parse_sire_pta_scores(sire_pta_scores_raw)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

        try:
            service_fee = BreedingService._parse_service_fee(data.get("service_fee", data.get("serviceFee")))
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

        insemination_time = BreedingService._extract_insemination_time(data)
        certificate_number = (data.get("certificate_number") or data.get("certificateNo") or "").strip() or None
        technician_name = (data.get("technician_name") or data.get("technicianName") or "").strip() or None
        owner_name = (data.get("owner_name") or data.get("ownerName") or "").strip() or None
        farm_location = (data.get("farm_location") or data.get("farmLocation") or "").strip() or None
        is_repeat_service = bool(data.get("is_repeat_service", data.get("isRepeatService", False)))

        milestones = ReproductionService.calculate_milestones(insemination_date)
        log = BreedingLogRepository.create(
            tenant_id=tenant_id,
            cow_id=livestock.id,
            inventory_semen_id=semen.id if semen else None,
            external_sire_code=resolved_external_sire_code,
            provided_by=provided_by,
            sire_pta_scores=sire_pta_scores,
            insemination_date=insemination_date,
            expected_calving_date=milestones["expected_calving_date"],
            status="Pending",
        )

        log.insemination_time = insemination_time
        log.certificate_number = certificate_number
        log.technician_name = technician_name
        log.owner_name = owner_name
        log.farm_location = farm_location
        log.service_fee = service_fee
        log.is_repeat_service = is_repeat_service
        log.certificate_image_url = (data.get("certificate_image_url") or data.get("certificateImageUrl") or "").strip() or None
        if heat_observation is not None:
            heat_observation.breeding_log_id = log.id
        db.session.commit()

        sire_label = semen.bull_name if semen else (resolved_external_sire_code or "Unknown sire")
        AnimalTimelineService.record_event(
            tenant_id=tenant_id,
            cow_id=livestock.id,
            event_type='breeding',
            title=f'Inseminated with {sire_label}',
            description=f'Status: {log.status} | Expected calving: {milestones["expected_calving_date"].isoformat()}',
            event_date=insemination_date,
            event_data={
                'breeding_log_id': log.id,
                'provided_by': log.provided_by,
                'expected_calving_date': milestones['expected_calving_date'].isoformat(),
                'pregnancy_check_date': milestones['pregnancy_check_date'].isoformat(),
                'status': log.status,
            },
        )

        response = BreedingService._build_insemination_payload(log, milestones)
        response["stock_level_remaining"] = stock_level_remaining

        schedule_pregnancy_check_reminder(
            tenant_id=tenant_id,
            cow_id=livestock.id,
            breeding_log_id=log.id,
            insemination_date=insemination_date,
        )

        return jsonify(response), 201

    @staticmethod
    def update_breeding_status(tenant_id: int, log_id: int, data: dict):
        status = BreedingService._normalize_status_input(data.get("status"))
        if status not in BreedingService.VALID_STATUSES:
            return jsonify({"error": "status must be one of Pending, Pregnant, Failed, Calved."}), 400

        log = BreedingLogRepository.get_by_id_for_tenant(log_id, tenant_id)
        if not log:
            return jsonify({"error": "Breeding log not found for this tenant."}), 404

        log.status = status

        livestock = CowRepository.get_by_livestock_id(log.cow_id, tenant_id=tenant_id)
        if livestock:
            BreedingService._sync_cow_status_with_outcome(livestock, log)

        db.session.commit()

        AnimalTimelineService.record_event(
            tenant_id=tenant_id,
            cow_id=log.cow_id,
            event_type='breeding_status_update',
            title=f'Breeding status changed to {status}',
            event_data={'breeding_log_id': log.id, 'status': status},
        )

        return jsonify({"message": "Breeding status updated.", "id": log.id, "status": log.status}), 200

    @staticmethod
    def _sync_cow_status_with_outcome(livestock, log) -> None:
        """Keeps the herd register's core status fields in step with breeding outcomes."""
        if log.status == "Pregnant":
            livestock.pregnancy_status = "Pregnant"
            livestock.due_date = log.expected_calving_date
        elif log.status == "Calved":
            livestock.pregnancy_status = "Open"
            livestock.due_date = None
            livestock.status = CowStatus.LACTATING
            if not livestock.last_calving_date:
                livestock.last_calving_date = date.today()
        elif log.status == "Failed":
            livestock.pregnancy_status = "Open"
            livestock.due_date = None

    @staticmethod
    def update_insemination_outcome(tenant_id: int, log_id: int, data: dict):
        status = BreedingService._normalize_status_input(data.get("status"))
        if status not in {"Pregnant", "Failed", "Calved"}:
            return jsonify({"error": "Invalid outcome status"}), 400

        log = BreedingLogRepository.get_by_id_for_tenant(log_id, tenant_id)
        if not log:
            return jsonify({"error": "Breeding log not found for this tenant."}), 404

        log.status = status

        livestock = CowRepository.get_by_livestock_id(log.cow_id, tenant_id=tenant_id)
        if not livestock:
            return jsonify({"error": "Livestock not found in registry."}), 404

        BreedingService._sync_cow_status_with_outcome(livestock, log)

        db.session.commit()

        AnimalTimelineService.record_event(
            tenant_id=tenant_id,
            cow_id=log.cow_id,
            event_type='breeding_status_update',
            title=f'Breeding status changed to {status}',
            event_data={'breeding_log_id': log.id, 'status': status},
        )

        return jsonify({"message": f"Insemination marked as {status}", "id": log.id, "status": log.status}), 200

    @staticmethod
    def bull_performance_summary(tenant_id: int):
        summary_rows = BreedingAnalyticsRepository.bull_conception_summary(tenant_id)
        payload = []

        for row in summary_rows:
            total_services = int(row.total_services or 0)
            pregnant_cases = int(row.pregnant_cases or 0)
            conception_rate = round((pregnant_cases / total_services) * 100, 2) if total_services else 0.0

            avg_milk = BreedingAnalyticsRepository.bull_avg_milk_volume(tenant_id, row.semen_id)
            avg_milk = round(float(avg_milk), 2) if avg_milk is not None else None

            avg_butterfat = BreedingAnalyticsRepository.bull_avg_butterfat(tenant_id, row.semen_id)
            avg_butterfat = round(float(avg_butterfat), 2) if avg_butterfat is not None else None

            payload.append(
                {
                    "semen_id": row.semen_id,
                    "bull_name": row.bull_name,
                    "straw_code": row.straw_code,
                    "total_services": total_services,
                    "pregnant_cases": pregnant_cases,
                    "conception_rate_percent": conception_rate,
                    "avg_milk_volume_liters_for_pregnant_progeny": avg_milk,
                    "avg_butterfat_pct_for_pregnant_progeny": avg_butterfat,
                }
            )

        return (
            jsonify(
                {
                    "summary": payload,
                    "note": "Performance summary now includes both milk volume and butterfat averages where data exists.",
                }
            ),
            200,
        )
