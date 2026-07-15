from __future__ import annotations
"""
Service for herd feeding plan calculation.
Single Responsibility: Calculate optimal feeding schedules for the herd based on individual cow targets.
Depends on repositories and calculation helpers.
"""
from decimal import Decimal
from app.repositories.yield_target_repo import YieldTargetRepository
from app.repositories.cow_repo import CowRepository
from app.services.feed_frequency_helper import FeedFrequencyHelper


class HerdFeedingPlanService:
    """Calculates herd-wide feeding plans from individual cow yield targets."""

    @staticmethod
    def calculate_from_cow_targets(tenant_id: int, milking_frequency: int | None = None) -> dict:
        """
        Calculate herd feeding plan from saved yield targets for LACTATING cows only.
        
        Returns:
        {
            "herd_total_target_liters": float,
            "total_meal_needed_kg": float,
            "total_milking_topup_kg": float,
            "per_milking_session_kg": float,
            "suggested_yard_feedings": int,
            "used_milking_frequency": int,
            "farmer_reasoning": str,
            "cow_breakdown": [
                {
                    "cow_id": int,
                    "cow_tag": str,
                    "cow_name": str,
                    "target_liters": float,
                    "feed_allocation_kg": float,
                    "topup_per_session_kg": float,
                },
                ...
            ],
            "active_lactating_count": int,
            "dry_or_inactive_count": int,
        }
        """
        # Get only LACTATING cows with active targets
        targets = YieldTargetRepository.get_all_for_lactating_cows(tenant_id=tenant_id)

        if not targets:
            raise ValueError("No active yield targets found for lactating cows in this herd.")

        # Aggregate herd-level targets
        total_herd_target = sum(float(t.target_liters) for t in targets)
        total_base_feed = sum(float(t.base_herd_feed_kg) for t in targets)

        # Calculate using helper (existing logic)
        herd_plan = FeedFrequencyHelper.calculate_milking_schedule(
            target_liters=total_herd_target,
            baseline_herd_meal_kg=total_base_feed,
            milking_frequency=milking_frequency,
        )

        # Build per-cow breakdown
        cow_breakdown = []
        per_session_kg = float(herd_plan["per_milking_session_kg"])

        for target in targets:
            cow = CowRepository.get_by_id(target.animal_id, tenant_id=tenant_id)

            # Proportional allocation based on individual target
            proportion = float(target.target_liters) / total_herd_target if total_herd_target > 0 else 0
            feed_allocation = float(herd_plan["total_dairy_meal_kg"]) * proportion

            cow_breakdown.append({
                "cow_id": target.animal_id,
                "cow_tag": cow.tag_number,
                "cow_name": cow.name,
                "target_liters": float(target.target_liters),
                "feed_allocation_kg": round(feed_allocation, 2),
                "topup_per_session_kg": round(per_session_kg * proportion, 2),
                "times_to_feed": target.times_to_feed_daily,
            })

        # Count herd composition
        all_cows = CowRepository.get_all_active_livestock(tenant_id=tenant_id)
        dry_or_inactive = len(all_cows) - len(targets)

        return {
            "herd_total_target_liters": round(total_herd_target, 2),
            "total_meal_needed_kg": float(herd_plan["total_dairy_meal_kg"]),
            "total_milking_topup_kg": float(herd_plan["extra_milking_topup_total_kg"]),
            "per_milking_session_kg": per_session_kg,
            "suggested_yard_feedings": int(herd_plan["suggested_yard_feedings"]),
            "used_milking_frequency": int(herd_plan["used_milking_frequency"]),
            "farmer_reasoning": herd_plan["farmer_reasoning"],
            "cow_breakdown": cow_breakdown,
            "active_lactating_count": len(targets),
            "dry_or_inactive_count": dry_or_inactive,
            "total_herd_count": len(all_cows),
        }

    @staticmethod
    def calculate_from_manual_targets(
        cow_targets: list[dict],
        baseline_herd_meal_kg: float = 4.0,
        milking_frequency: int | None = None,
    ) -> dict:
        """
        Calculate herd feeding plan from manually provided cow targets.
        
        Args:
            cow_targets: List of dicts with 'cow_id', 'target_liters', optionally 'cow_tag'
            baseline_herd_meal_kg: Base meal for the herd
            milking_frequency: Optional override for feeding frequency
        
        Returns: Same structure as calculate_from_cow_targets
        """
        if not cow_targets or len(cow_targets) == 0:
            raise ValueError("At least one cow target is required.")

        # Validate and aggregate
        total_target = 0
        aggregated_targets = []

        for entry in cow_targets:
            cow_id = entry.get('cow_id')
            target_liters = entry.get('target_liters')

            if not cow_id or target_liters is None:
                raise ValueError("Each cow target must have 'cow_id' and 'target_liters'.")

            try:
                target_liters = float(target_liters)
            except (TypeError, ValueError):
                raise ValueError(f"target_liters for cow {cow_id} must be numeric.")

            if target_liters <= 0:
                raise ValueError(f"target_liters for cow {cow_id} must be > 0.")

            total_target += target_liters
            aggregated_targets.append({
                "cow_id": cow_id,
                "target_liters": target_liters,
            })

        # Calculate using helper
        herd_plan = FeedFrequencyHelper.calculate_milking_schedule(
            target_liters=total_target,
            baseline_herd_meal_kg=baseline_herd_meal_kg,
            milking_frequency=milking_frequency,
        )

        # Build per-cow breakdown
        cow_breakdown = []
        per_session_kg = float(herd_plan["per_milking_session_kg"])

        for target in aggregated_targets:
            cow_id = target["cow_id"]
            target_liters = target["target_liters"]
            proportion = target_liters / total_target if total_target > 0 else 0
            feed_allocation = float(herd_plan["total_dairy_meal_kg"]) * proportion

            cow_breakdown.append({
                "cow_id": cow_id,
                "target_liters": target_liters,
                "feed_allocation_kg": round(feed_allocation, 2),
                "topup_per_session_kg": round(per_session_kg * proportion, 2),
            })

        return {
            "herd_total_target_liters": round(total_target, 2),
            "total_meal_needed_kg": float(herd_plan["total_dairy_meal_kg"]),
            "total_milking_topup_kg": float(herd_plan["extra_milking_topup_total_kg"]),
            "per_milking_session_kg": per_session_kg,
            "suggested_yard_feedings": int(herd_plan["suggested_yard_feedings"]),
            "used_milking_frequency": int(herd_plan["used_milking_frequency"]),
            "farmer_reasoning": herd_plan["farmer_reasoning"],
            "cow_breakdown": cow_breakdown,
            "active_cow_count": len(aggregated_targets),
        }
