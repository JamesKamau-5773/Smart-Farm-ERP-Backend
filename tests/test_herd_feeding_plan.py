"""
Tests for HerdFeedingPlanService - Herd Planning Logic
Tests: Aggregation, per-cow breakdown, and plan generation
"""
import pytest
from app.models.livestock import Cow, CowStatus
from app.services.yield_target_service import YieldTargetService
from app.services.herd_feeding_plan_service import HerdFeedingPlanService
from app import db


@pytest.fixture
def sample_herd():
    """Create a sample herd with multiple lactating cows."""
    cows = []
    for i in range(3):
        cow = Cow(
            tenant_id=1,
            tag_number=f'HERD-{i+1:03d}',
            name=f'Herd Cow {i+1}',
            breed_status='Foundation',
            date_of_birth='2020-01-01',
            current_status=CowStatus.LACTATING,
            is_active=True,
        )
        db.session.add(cow)
        cows.append(cow)
    db.session.commit()
    return cows


class TestHerdFeedingPlanService:
    """Service tests for HerdFeedingPlanService."""

    def test_calculate_from_manual_targets(self, app_context):
        """Test calculating herd plan from manual cow targets."""
        cow_targets = [
            {"cow_id": 1, "target_liters": 2.5},
            {"cow_id": 2, "target_liters": 2.0},
            {"cow_id": 3, "target_liters": 1.8},
        ]
        plan = HerdFeedingPlanService.calculate_from_manual_targets(
            cow_targets=cow_targets,
            baseline_herd_meal_kg=4.0,
        )
        assert plan['herd_total_target_liters'] == 6.3
        assert plan['active_cow_count'] == 3
        assert len(plan['cow_breakdown']) == 3
        assert plan['suggested_yard_feedings'] in {2, 3, 4}

    def test_calculate_from_manual_targets_proportional_allocation(self, app_context):
        """Test that feed allocation is proportional to milk targets."""
        cow_targets = [
            {"cow_id": 1, "target_liters": 2.0},  # 50% of total
            {"cow_id": 2, "target_liters": 2.0},  # 50% of total
        ]
        plan = HerdFeedingPlanService.calculate_from_manual_targets(
            cow_targets=cow_targets,
            baseline_herd_meal_kg=0.0,
        )
        total_meal = plan['total_meal_needed_kg']
        # Each cow should get ~50% of total meal
        cow1_allocation = plan['cow_breakdown'][0]['feed_allocation_kg']
        cow2_allocation = plan['cow_breakdown'][1]['feed_allocation_kg']

        assert abs(cow1_allocation - total_meal / 2) < 0.1
        assert abs(cow2_allocation - total_meal / 2) < 0.1

    def test_calculate_from_manual_targets_empty_raises_error(self, app_context):
        """Test that empty cow targets list raises error."""
        with pytest.raises(ValueError, match="At least one"):
            HerdFeedingPlanService.calculate_from_manual_targets(
                cow_targets=[],
                baseline_herd_meal_kg=4.0,
            )

    def test_calculate_from_manual_targets_invalid_data(self, app_context):
        """Test validation of cow target data."""
        with pytest.raises(ValueError, match="must have"):
            HerdFeedingPlanService.calculate_from_manual_targets(
                cow_targets=[{"cow_id": 1}],  # Missing target_liters
                baseline_herd_meal_kg=4.0,
            )

    def test_calculate_from_manual_targets_negative_liters(self, app_context):
        """Test that negative liters are rejected."""
        with pytest.raises(ValueError, match="must be > 0"):
            HerdFeedingPlanService.calculate_from_manual_targets(
                cow_targets=[{"cow_id": 1, "target_liters": -1.0}],
                baseline_herd_meal_kg=4.0,
            )

    def test_calculate_from_cow_targets_saved_targets(self, app_context, sample_herd):
        """Test calculating plan from saved yield targets in DB."""
        # Set targets for all cows
        for cow in sample_herd:
            YieldTargetService.set_yield_target(
                tenant_id=1,
                cow_id=cow.id,
                target_liters=2.5,
            )

        plan = HerdFeedingPlanService.calculate_from_cow_targets(tenant_id=1)

        assert plan['herd_total_target_liters'] == 7.5
        assert plan['active_lactating_count'] == 3
        assert len(plan['cow_breakdown']) == 3
        assert 'farmer_reasoning' in plan

    def test_calculate_from_cow_targets_excludes_dry_cows(self, app_context, sample_herd):
        """Test that dry cows are excluded from plan."""
        # Set first cow to dry
        sample_herd[0].current_status = CowStatus.DRY
        db.session.commit()

        # Set targets for all cows (service will validate)
        for cow in sample_herd:
            YieldTargetService.set_yield_target(
                tenant_id=1,
                cow_id=cow.id,
                target_liters=2.5,
            )

        plan = HerdFeedingPlanService.calculate_from_cow_targets(tenant_id=1)

        # Only 2 lactating cows should be in the plan
        assert plan['herd_total_target_liters'] == 5.0  # 2 * 2.5
        assert plan['active_lactating_count'] == 2
        assert plan['dry_or_inactive_count'] == 1

    def test_calculate_from_cow_targets_no_targets_raises_error(self, app_context, sample_herd):
        """Test that no targets raises error."""
        with pytest.raises(ValueError, match="No active yield targets"):
            HerdFeedingPlanService.calculate_from_cow_targets(tenant_id=1)

    def test_calculate_plan_high_load_frequency(self, app_context):
        """Test that high milk load recommends 4 daily feedings."""
        # Very high targets should trigger 4 feedings
        cow_targets = [
            {"cow_id": 1, "target_liters": 25.0},  # Very high
        ]
        plan = HerdFeedingPlanService.calculate_from_manual_targets(
            cow_targets=cow_targets,
            baseline_herd_meal_kg=4.0,
        )
        assert plan['suggested_yard_feedings'] == 4

    def test_calculate_plan_low_load_frequency(self, app_context):
        """Test that low milk load recommends 2 daily feedings."""
        # Low targets should trigger 2 feedings
        cow_targets = [
            {"cow_id": 1, "target_liters": 12.0},  # Just above baseline
        ]
        plan = HerdFeedingPlanService.calculate_from_manual_targets(
            cow_targets=cow_targets,
            baseline_herd_meal_kg=4.0,
        )
        assert plan['suggested_yard_feedings'] == 2

    def test_calculate_plan_custom_frequency_override(self, app_context):
        """Test that custom milking frequency overrides recommendation."""
        cow_targets = [
            {"cow_id": 1, "target_liters": 15.0},
        ]
        plan = HerdFeedingPlanService.calculate_from_manual_targets(
            cow_targets=cow_targets,
            baseline_herd_meal_kg=4.0,
            milking_frequency=4,
        )
        assert plan['used_milking_frequency'] == 4
