"""
Service layer for animal yield target business logic.
Follows SRP: orchestrates repository, validation, and calculation logic.
"""

from __future__ import annotations
from decimal import Decimal

from app.models.livestock import Cow, CowStatus
from app.repositories.animal_yield_target_repo import AnimalYieldTargetRepository
from app.repositories.cow_repo import CowRepository
from app.services.feed_frequency_helper import FeedFrequencyHelper


class AnimalYieldTargetService:
    """Business logic for managing per-cow yield targets and herd feeding plans."""

    @staticmethod
    def set_yield_target(
        tenant_id: int,
        cow_id: int,
        target_liters: float,
        validate_status: bool = True
    ) -> dict:
        """Set or update yield target for a cow.
        
        Args:
            tenant_id: Tenant ID
            cow_id: Cow ID
            target_liters: Target milk production in liters
            validate_status: If True, validate cow status is LACTATING
            
        Returns:
            dict with created/updated target and validation warnings
            
        Raises:
            ValueError: If cow not found, status invalid, or target invalid
        """
        # Validate target input
        try:
            target_liters = float(target_liters)
        except (TypeError, ValueError):
            raise ValueError('target_liters must be a valid number.')
        
        if target_liters <= 0:
            raise ValueError('target_liters must be greater than 0.')

        # Fetch and validate cow
        cow = CowRepository.get_by_id(cow_id, tenant_id=tenant_id)
        if not cow:
            raise ValueError(f'Cow {cow_id} not found for this tenant.')

        warnings = []
        if validate_status and cow.current_status != CowStatus.LACTATING:
            warnings.append(
                f'Cow {cow.tag_number} is {cow.current_status}, not LACTATING. '
                'Target will be saved but feeding plan may exclude this cow.'
            )

        # Create/update target - this also commits
        target = AnimalYieldTargetRepository.create_or_update(
            tenant_id=tenant_id,
            cow_id=cow_id,
            target_liters=target_liters
        )

        # Set is_active based on cow status and update in database
        target.is_active = cow.current_status == CowStatus.LACTATING
        
        from app import db
        db.session.merge(target)  # Re-attach to session after repository's commit
        db.session.commit()  # Persist is_active change

        return {
            'target_id': target.id,
            'cow_id': target.animal_id,
            'tag_number': cow.tag_number,
            'target_liters': float(target.target_liters),
            'status': target.status,
            'is_active': target.is_active,
            'updated_at': target.updated_at.isoformat() if target.updated_at else None,
            'warnings': warnings
        }

    @staticmethod
    def get_cow_target(tenant_id: int, cow_id: int) -> dict | None:
        """Get yield target for a specific cow."""
        target = AnimalYieldTargetRepository.get_by_cow_id(cow_id, tenant_id=tenant_id)
        if not target:
            return None

        cow = CowRepository.get_by_id(target.animal_id, tenant_id=tenant_id)
        return {
            'target_id': target.id,
            'cow_id': target.animal_id,
            'tag_number': cow.tag_number if cow else None,
            'target_liters': float(target.target_liters),
            'times_to_feed_daily': target.times_to_feed_daily,
            'base_herd_feed_kg': float(target.base_herd_feed_kg),
            'milking_topup_kg': float(target.milking_topup_kg),
            'status': target.status,
            'is_active': target.is_active,
            'updated_at': target.updated_at.isoformat() if target.updated_at else None
        }

    @staticmethod
    def list_herd_targets(tenant_id: int) -> list[dict]:
        """List all active yield targets for the herd with cow details."""
        targets = AnimalYieldTargetRepository.get_active_targets_for_herd(tenant_id=tenant_id)
        
        result = []
        for target in targets:
            cow = CowRepository.get_by_id(target.animal_id, tenant_id=tenant_id)
            result.append({
                'target_id': target.id,
                'cow_id': target.animal_id,
                'tag_number': cow.tag_number if cow else None,
                'cow_name': cow.name if cow else None,
                'target_liters': float(target.target_liters),
                'times_to_feed_daily': target.times_to_feed_daily,
                'status': target.status
            })
        
        return result

    @staticmethod
    def calculate_herd_feeding_plan(
        tenant_id: int,
        baseline_herd_meal_kg: float = 4.0,
        milking_frequency: int | None = None,
        use_saved_targets: bool = True
    ) -> dict:
        """Calculate feeding plan aggregating all per-cow targets.
        
        Args:
            tenant_id: Tenant ID
            baseline_herd_meal_kg: Base daily meal for entire herd
            milking_frequency: Explicit milking frequency (2, 3, or 4) or None for auto
            use_saved_targets: If True, use saved AnimalYieldTarget records
            
        Returns:
            dict with aggregated feeding plan and per-cow breakdown
            
        Raises:
            ValueError: If no targets available or calculation fails
        """
        if use_saved_targets:
            targets = AnimalYieldTargetRepository.get_active_targets_for_herd(tenant_id=tenant_id)
            if not targets:
                raise ValueError(
                    'No active yield targets found for lactating cows. '
                    'Set targets first using POST /api/v1/animals/{cow_id}/yield-target'
                )

            # Build per-cow target list
            cow_targets = []
            for target in targets:
                cow = CowRepository.get_by_id(target.animal_id, tenant_id=tenant_id)
                if cow:
                    cow_targets.append({
                        'cow_id': target.animal_id,
                        'tag': cow.tag_number,
                        'target_liters': float(target.target_liters)
                    })
        else:
            raise ValueError('Non-saved target mode not yet implemented.')

        if not cow_targets:
            raise ValueError('No active cows with yield targets.')

        # Calculate herd-level plan
        total_target = sum(ct['target_liters'] for ct in cow_targets)
        
        try:
            plan = FeedFrequencyHelper.calculate_milking_schedule(
                target_liters=total_target,
                baseline_herd_meal_kg=baseline_herd_meal_kg,
                milking_frequency=milking_frequency
            )
        except ValueError as e:
            raise ValueError(f'Feed calculation failed: {str(e)}')

        # Calculate per-cow allocation (proportional to target)
        total_meal_needed = Decimal(str(plan['total_dairy_meal_kg']))
        total_topup = Decimal(str(plan['extra_milking_topup_total_kg']))
        
        per_cow_breakdown = []
        for cow_target in cow_targets:
            proportion = Decimal(str(cow_target['target_liters'])) / Decimal(str(total_target))
            feed_allocation = float(total_meal_needed * proportion)
            topup_allocation = float(total_topup * proportion)
            
            per_cow_breakdown.append({
                'cow_id': cow_target['cow_id'],
                'tag': cow_target['tag'],
                'target_liters': cow_target['target_liters'],
                'feed_allocation_kg': round(feed_allocation, 2),
                'topup_kg': round(topup_allocation, 2)
            })

        return {
            'total_herd_target_liters': total_target,
            'total_meal_needed_kg': plan['total_dairy_meal_kg'],
            'base_herd_mix_kg': plan['base_herd_mix_kg'],
            'extra_milking_topup_total_kg': plan['extra_milking_topup_total_kg'],
            'per_milking_session_kg': plan['per_milking_session_kg'],
            'suggested_yard_feedings': plan['suggested_yard_feedings'],
            'used_milking_frequency': plan['used_milking_frequency'],
            'farmer_reasoning': plan['farmer_reasoning'],
            'number_of_cows': len(cow_targets),
            'per_cow_breakdown': per_cow_breakdown
        }

    @staticmethod
    def deactivate_target(tenant_id: int, target_id: int) -> dict:
        """Deactivate a yield target (cow may be going dry)."""
        success = AnimalYieldTargetRepository.deactivate(target_id, tenant_id=tenant_id)
        if not success:
            raise ValueError(f'Yield target {target_id} not found for this tenant.')
        
        return {'message': 'Yield target deactivated successfully.'}

    @staticmethod
    def delete_target(tenant_id: int, target_id: int) -> dict:
        """Delete a yield target completely."""
        success = AnimalYieldTargetRepository.delete(target_id, tenant_id=tenant_id)
        if not success:
            raise ValueError(f'Yield target {target_id} not found for this tenant.')
        
        return {'message': 'Yield target deleted successfully.'}

    @staticmethod
    def handle_cow_status_change(cow_id: int, new_status: str, tenant_id: int) -> None:
        """Handle status change events (e.g., LACTATING -> DRY).
        
        When a cow changes status, automatically deactivate its yield target.
        This keeps the herd feeding plan accurate.
        """
        if new_status != CowStatus.LACTATING:
            target = AnimalYieldTargetRepository.get_by_cow_id(cow_id, tenant_id=tenant_id)
            if target and target.status == 'Active':
                AnimalYieldTargetRepository.deactivate(target.id, tenant_id=tenant_id)
