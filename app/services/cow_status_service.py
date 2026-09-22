from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING
from dateutil.relativedelta import relativedelta

from app.models.livestock import CowStatus, LactationCycle
if TYPE_CHECKING:
    from app.models.livestock import Cow
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
    def compute_current_status(cow: "Cow") -> str:
        """
        Computes the current status of a cow, respecting manual overrides
        for 'Lactating' or 'Dry' status, before falling back to derived logic.
        """
        # 1. Pregnancy is the primary reproductive status, including for
        # cows that are still lactating when pregnancy is confirmed.
        if cow.pregnancy_status == 'Pregnant':
            return CowStatusService.PREGNANT

        # 2. Respect explicit status set by calving or drying-off events.
        if cow.status in (CowStatus.LACTATING, CowStatus.DRY):
            return cow.status

        # 3. Check for historical lactation cycles to determine status.
        latest_cycle = (
            LactationCycle.query
            .filter(LactationCycle.cow_id == cow.id)
            .order_by(LactationCycle.actual_calving_date.desc())
            .first()
        )

        if latest_cycle:
            # Has calved before. Is she currently milking or dry?
            return CowStatus.LACTATING if latest_cycle.end_date is None else CowStatus.DRY

        # 4. No calving history, so she's a Calf or Heifer based on age.
        if not cow.date_of_birth:
            return CowStatus.HEIFER  # Default for unknown age

        age = relativedelta(date.today(), cow.date_of_birth)
        # Industry standard: calf until ~1 year, then heifer until first calving.
        return CowStatus.CALF if age.years < 1 else CowStatus.HEIFER

    @staticmethod
    def compute_pregnancy_status(cow, tenant_id: int) -> str:
        # A calf cannot be pregnant. Determine if it's a calf by age.
        age = relativedelta(date.today(), cow.date_of_birth) if cow.date_of_birth else None
        if age and age.years < 1:
            return CowStatusService.NOT_APPLICABLE

        # The cow.pregnancy_status field is the authoritative source, updated by breeding workflows.
        if cow.pregnancy_status == "Pregnant":
            return CowStatusService.PREGNANT

        # Fallback to breeding log for 'Bred - Pending' status if master record is not yet 'Pregnant'.
        latest_log = BreedingLogRepository.get_most_recent_for_cow(cow.id, tenant_id)
        if latest_log and latest_log.status == "Pending":
            return CowStatusService.BRED_PENDING

        # Default to Open if not pregnant and no pending insemination.
        return CowStatusService.OPEN

    @staticmethod
    def compute_days_in_milk(cow) -> int | None:
        if CowStatusService.compute_current_status(cow) != CowStatus.LACTATING:
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
        calving_date = (
            latest_cycle.actual_calving_date
            if latest_cycle is not None
            else cow.last_calving_date
        )
        if calving_date is None:
            return None
        return max((date.today() - calving_date).days, 0)

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
            "current_status": CowStatusService.compute_current_status(cow),
            "pregnancy_status": CowStatusService.compute_pregnancy_status(cow, tenant_id),
            "days_in_milk": CowStatusService.compute_days_in_milk(cow),
            "days_open": CowStatusService.compute_days_open(cow, tenant_id),
        }
