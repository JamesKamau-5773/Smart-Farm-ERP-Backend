from __future__ import annotations
"""
Service for yield target business logic.
Single Responsibility: Encapsulate business rules around animal production targets and herd feeding plans.
Depends on repositories for data access.
"""
from decimal import Decimal
from app.repositories.yield_target_repo import YieldTargetRepository
from app.repositories.cow_repo import CowRepository
from app.models.livestock import Cow, CowStatus
from app.models.supply import MilkLog
from app import db
from datetime import datetime, timezone, timedelta


class YieldTargetService:
    """Business logic for managing individual cow yield targets."""

    @staticmethod
    def validate_cow_for_target(cow_id: int, tenant_id: int) -> tuple[bool, str]:
        """
        Validate if a cow is eligible for yield target assignment.
        Returns: (is_valid, reason_or_empty)
        """
        cow = CowRepository.get_by_id(cow_id, tenant_id=tenant_id)
        if not cow:
            return False, f"Cow {cow_id} not found."

        if not cow.is_active:
            return False, f"Cow {cow.tag_number} is not active."

        # Allow LACTATING and DRY cows (DRY can transition to LACTATING)
        allowed_statuses = {CowStatus.LACTATING, CowStatus.DRY}
        if cow.current_status not in allowed_statuses:
            return False, f"Cow {cow.tag_number} is in {cow.current_status} status. Only LACTATING or DRY cows can have targets."

        return True, ""

    @staticmethod
    def set_yield_target(
        tenant_id: int,
        cow_id: int,
        target_liters: float,
        base_herd_feed_kg: float = 0.0,
        times_to_feed_daily: int = 2,
    ) -> dict:
        """
        Create or update yield target for a cow.
        Returns: target_id, cow_info, and calculation details.
        """
        # Validate cow eligibility
        is_valid, reason = YieldTargetService.validate_cow_for_target(cow_id, tenant_id)
        if not is_valid:
            raise ValueError(reason)

        # Validate numeric inputs
        try:
            target_liters = float(target_liters)
            base_herd_feed_kg = float(base_herd_feed_kg)
        except (TypeError, ValueError):
            raise ValueError("target_liters and base_herd_feed_kg must be numeric values.")

        if target_liters <= 0:
            raise ValueError("target_liters must be greater than 0.")
        if base_herd_feed_kg < 0:
            raise ValueError("base_herd_feed_kg cannot be negative.")
        if times_to_feed_daily not in {2, 3, 4}:
            raise ValueError("times_to_feed_daily must be 2, 3, or 4.")

        # Check if target already exists
        existing = YieldTargetRepository.get_by_animal_id(cow_id, tenant_id=tenant_id)
        cow = CowRepository.get_by_id(cow_id, tenant_id=tenant_id)

        if existing:
            # Update existing
            updated = YieldTargetRepository.update(
                existing.id,
                tenant_id=tenant_id,
                target_liters=target_liters,
                base_herd_feed_kg=base_herd_feed_kg,
                times_to_feed_daily=times_to_feed_daily,
            )
            # Set is_active based on cow status and persist
            updated.is_active = cow.current_status == CowStatus.LACTATING
            db.session.merge(updated)  # Re-attach after repository's commit
            db.session.commit()  # Persist is_active change
            
            return {
                "id": updated.id,
                "cow_id": cow_id,
                "cow_tag": cow.tag_number,
                "target_liters": float(updated.target_liters),
                "base_herd_feed_kg": float(updated.base_herd_feed_kg),
                "times_to_feed_daily": updated.times_to_feed_daily,
                "status": updated.status,
                "is_active": updated.is_active,
                "updated_at": updated.updated_at.isoformat() if updated.updated_at else None,
                "action": "updated",
            }
        else:
            # Create new
            target = YieldTargetRepository.create(
                tenant_id=tenant_id,
                animal_id=cow_id,
                target_liters=target_liters,
                base_herd_feed_kg=base_herd_feed_kg,
                times_to_feed_daily=times_to_feed_daily,
            )
            # Set is_active based on cow status and persist
            target.is_active = cow.current_status == CowStatus.LACTATING
            db.session.merge(target)  # Re-attach after repository's commit
            db.session.commit()  # Persist is_active change
            
            return {
                "id": target.id,
                "cow_id": cow_id,
                "cow_tag": cow.tag_number,
                "target_liters": float(target.target_liters),
                "base_herd_feed_kg": float(target.base_herd_feed_kg),
                "times_to_feed_daily": target.times_to_feed_daily,
                "status": target.status,
                "is_active": target.is_active,
                "updated_at": target.updated_at.isoformat() if target.updated_at else None,
                "action": "created",
            }

    @staticmethod
    def get_yield_target(tenant_id: int, cow_id: int) -> dict | None:
        """Fetch yield target for a specific cow."""
        target = YieldTargetRepository.get_by_animal_id(cow_id, tenant_id=tenant_id)
        if not target:
            return None

        cow = CowRepository.get_by_id(cow_id, tenant_id=tenant_id)
        return {
            "id": target.id,
            "cow_id": cow_id,
            "cow_tag": cow.tag_number,
            "cow_name": cow.name,
            "cow_status": cow.current_status,
            "target_liters": float(target.target_liters),
            "base_herd_feed_kg": float(target.base_herd_feed_kg),
            "times_to_feed_daily": target.times_to_feed_daily,
            "status": target.status,
            "is_active": target.is_active,
            "updated_at": target.updated_at.isoformat() if target.updated_at else None,
        }

    @staticmethod
    def get_all_yield_targets(tenant_id: int) -> list[dict]:
        """List all active yield targets for the herd."""
        targets = YieldTargetRepository.get_all_active(tenant_id=tenant_id)
        result = []
        for target in targets:
            cow = CowRepository.get_by_id(target.animal_id, tenant_id=tenant_id)
            result.append({
                "id": target.id,
                "cow_id": target.animal_id,
                "cow_tag": cow.tag_number,
                "cow_name": cow.name,
                "cow_status": cow.current_status,
                "target_liters": float(target.target_liters),
                "base_herd_feed_kg": float(target.base_herd_feed_kg),
                "times_to_feed_daily": target.times_to_feed_daily,
                "status": target.status,
                "is_active": target.is_active,
                "updated_at": target.updated_at.isoformat() if target.updated_at else None,
            })
        return result

    @staticmethod
    def deactivate_yield_target(tenant_id: int, cow_id: int) -> dict:
        """Deactivate yield target for a cow."""
        target = YieldTargetRepository.get_by_animal_id(cow_id, tenant_id=tenant_id)
        if not target:
            raise ValueError(f"No yield target found for cow {cow_id}.")

        deactivated = YieldTargetRepository.deactivate(target.id, tenant_id=tenant_id)
        cow = CowRepository.get_by_id(cow_id, tenant_id=tenant_id)
        return {
            "id": deactivated.id,
            "cow_id": cow_id,
            "cow_tag": cow.tag_number,
            "status": deactivated.status,
            "message": f"Yield target for {cow.tag_number} deactivated.",
        }
