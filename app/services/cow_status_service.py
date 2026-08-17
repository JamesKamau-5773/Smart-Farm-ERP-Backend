from __future__ import annotations

from datetime import date

from app.models.livestock import CowStatus, LactationCycle
from app.repositories.breeding_repo import BreedingLogRepository


class CowStatusService:
    """Computes herd-register display fields the frontend must never derive itself.

    current_status only tracks lifecycle/reproductive stage (Calf/Heifer/Lactating/
    Dry/Pregnant); pregnancy status, days-in-milk, and days-open are derived here
    from the breeding_logs and lactation_cycles tables so every consumer (herd list,
    animal passport, PDF export) reports the same backend-owned truth.
    """

    NOT_APPLICABLE = "Not Applicable"
    OPEN = "Open"
    PREGNANT = "Pregnant"
    BRED_PENDING = "Bred - Pending"

    @staticmethod
    def compute_pregnancy_status(cow, tenant_id: int) -> str:
        if cow.current_status == CowStatus.CALF:
            return CowStatusService.NOT_APPLICABLE
        if cow.current_status == "Pregnant":
            return CowStatusService.PREGNANT

        latest_log = BreedingLogRepository.get_most_recent_for_cow(cow.id, tenant_id)
        if latest_log is None:
            return CowStatusService.OPEN
        if latest_log.status == "Pending":
            return CowStatusService.BRED_PENDING
        return CowStatusService.OPEN

    @staticmethod
    def compute_days_in_milk(cow) -> int | None:
        if cow.current_status != CowStatus.LACTATING:
            return None

        latest_cycle = (
            LactationCycle.query
            .filter(
                LactationCycle.cow_id == cow.id,
                LactationCycle.actual_calving_date.isnot(None),
            )
            .order_by(LactationCycle.actual_calving_date.desc())
            .first()
        )
        if latest_cycle is None or latest_cycle.actual_calving_date is None:
            return None
        return max((date.today() - latest_cycle.actual_calving_date).days, 0)

    @staticmethod
    def compute_days_open(cow, tenant_id: int) -> int | None:
        latest_cycle = (
            LactationCycle.query
            .filter(
                LactationCycle.cow_id == cow.id,
                LactationCycle.actual_calving_date.isnot(None),
            )
            .order_by(LactationCycle.actual_calving_date.desc())
            .first()
        )
        if latest_cycle is None or latest_cycle.actual_calving_date is None:
            return None

        latest_pregnant_log = BreedingLogRepository.get_most_recent_pregnant_for_cow(cow.id, tenant_id)
        if latest_pregnant_log is not None and latest_pregnant_log.insemination_date is not None:
            return max((latest_pregnant_log.insemination_date - latest_cycle.actual_calving_date).days, 0)

        latest_log = BreedingLogRepository.get_most_recent_for_cow(cow.id, tenant_id)
        if latest_log is None or latest_log.insemination_date is None:
            return max((date.today() - latest_cycle.actual_calving_date).days, 0)

        return max((date.today() - latest_cycle.actual_calving_date).days, 0)

    @staticmethod
    def compute_status_fields(cow, tenant_id: int) -> dict:
        return {
            "pregnancy_status": CowStatusService.compute_pregnancy_status(cow, tenant_id),
            "days_in_milk": CowStatusService.compute_days_in_milk(cow),
            "days_open": CowStatusService.compute_days_open(cow, tenant_id),
        }
