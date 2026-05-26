from datetime import date
from decimal import Decimal

from flask import jsonify

from app.repositories.breeding_repo import (
    BreedingAnalyticsRepository,
    BreedingLogRepository,
    SemenInventoryRepository,
)
from app.repositories.cow_repo import CowRepository
from app.services.reproduction_service import ReproductionService


class BreedingService:
    VALID_STATUSES = {"Pending", "Pregnant", "Failed"}

    @staticmethod
    def _to_float(value):
        if isinstance(value, Decimal):
            return float(value)
        return value

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
        livestock_id = data.get("cow_id")
        semen_id = data.get("semen_id")
        insemination_date_raw = data.get("insemination_date")

        if not livestock_id or not semen_id or not insemination_date_raw:
            return jsonify({"error": "cow_id, semen_id, and insemination_date are required."}), 400

        try:
            livestock_id = int(livestock_id)
            semen_id = int(semen_id)
            insemination_date = date.fromisoformat(str(insemination_date_raw))
        except (ValueError, TypeError):
            return jsonify({"error": "Invalid cow_id, semen_id, or insemination_date format (YYYY-MM-DD)."}), 400

        livestock = CowRepository.get_by_id(livestock_id)
        if not livestock:
            return jsonify({"error": "Cow not found."}), 404

        semen = SemenInventoryRepository.get_by_id_for_tenant(semen_id, tenant_id)
        if not semen:
            return jsonify({"error": "Semen inventory item not found for this tenant."}), 404

        if semen.stock_level <= 0:
            return jsonify({"error": "No semen straws left for this inventory item."}), 400

        milestones = ReproductionService.calculate_milestones(insemination_date)
        log = BreedingLogRepository.create(
            tenant_id=tenant_id,
            cow_id=livestock_id,
            semen_id=semen_id,
            insemination_date=insemination_date,
            expected_calving_date=milestones["expected_calving_date"],
            status="Pending",
        )

        semen.stock_level -= 1
        SemenInventoryRepository.save()

        return jsonify(
            {
                "message": "Insemination logged successfully.",
                "breeding_log_id": log.id,
                "expected_calving_date": milestones["expected_calving_date"].isoformat(),
                "stock_level_remaining": semen.stock_level,
            }
        ), 201

    @staticmethod
    def update_breeding_status(tenant_id: int, log_id: int, data: dict):
        status = (data.get("status") or "").strip().title()
        if status not in BreedingService.VALID_STATUSES:
            return jsonify({"error": "status must be one of Pending, Pregnant, Failed."}), 400

        log = BreedingLogRepository.get_by_id_for_tenant(log_id, tenant_id)
        if not log:
            return jsonify({"error": "Breeding log not found for this tenant."}), 404

        log.status = status
        BreedingLogRepository.save()

        return jsonify({"message": "Breeding status updated.", "id": log.id, "status": log.status}), 200

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
