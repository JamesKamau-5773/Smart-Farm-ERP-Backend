"""
Tests for YieldTargetService - Business Logic Layer
Tests: Validation, target management, and constraints
"""
import pytest
from app.models.livestock import Cow, CowStatus
from app.services.yield_target_service import YieldTargetService
from app import db


@pytest.fixture
def lactating_cow(tenant_id=1):
    """Create a lactating cow for testing."""
    cow = Cow(
        tenant_id=tenant_id,
        tag_number='LACT-001',
        name='Lactating Cow',
        breed_status='Foundation',
        date_of_birth='2020-01-01',
        current_status=CowStatus.LACTATING,
        is_active=True,
    )
    db.session.add(cow)
    db.session.commit()
    return cow


@pytest.fixture
def dry_cow(tenant_id=1):
    """Create a dry cow for testing."""
    cow = Cow(
        tenant_id=tenant_id,
        tag_number='DRY-001',
        name='Dry Cow',
        breed_status='Foundation',
        date_of_birth='2020-01-01',
        current_status=CowStatus.DRY,
        is_active=True,
    )
    db.session.add(cow)
    db.session.commit()
    return cow


@pytest.fixture
def calf(tenant_id=1):
    """Create a calf for testing (should not be eligible for targets)."""
    cow = Cow(
        tenant_id=tenant_id,
        tag_number='CALF-001',
        name='Young Calf',
        breed_status='Foundation',
        date_of_birth='2025-01-01',
        current_status=CowStatus.CALF,
        is_active=True,
    )
    db.session.add(cow)
    db.session.commit()
    return cow


class TestYieldTargetService:
    """Service tests for YieldTargetService."""

    def test_set_yield_target_creates_new(self, app_context, lactating_cow):
        """Test creating a new yield target via service."""
        result = YieldTargetService.set_yield_target(
            tenant_id=1,
            cow_id=lactating_cow.id,
            target_liters=2.5,
            base_herd_feed_kg=0.5,
            times_to_feed_daily=2,
        )
        assert result['action'] == 'created'
        assert result['cow_id'] == lactating_cow.id
        assert result['target_liters'] == 2.5
        assert result['status'] == 'Active'

    def test_set_yield_target_updates_existing(self, app_context, lactating_cow):
        """Test updating existing yield target."""
        # Create first
        result1 = YieldTargetService.set_yield_target(
            tenant_id=1,
            cow_id=lactating_cow.id,
            target_liters=2.5,
        )
        # Update
        result2 = YieldTargetService.set_yield_target(
            tenant_id=1,
            cow_id=lactating_cow.id,
            target_liters=3.5,
        )
        assert result2['action'] == 'updated'
        assert result2['target_liters'] == 3.5
        assert result1['id'] == result2['id']  # Same target

    def test_validate_cow_for_target_lactating_ok(self, app_context, lactating_cow):
        """Test that LACTATING cows are eligible."""
        is_valid, reason = YieldTargetService.validate_cow_for_target(lactating_cow.id, tenant_id=1)
        assert is_valid is True
        assert reason == ""

    def test_validate_cow_for_target_dry_ok(self, app_context, dry_cow):
        """Test that DRY cows are eligible (can transition to lactating)."""
        is_valid, reason = YieldTargetService.validate_cow_for_target(dry_cow.id, tenant_id=1)
        assert is_valid is True
        assert reason == ""

    def test_validate_cow_for_target_calf_rejected(self, app_context, calf):
        """Test that CALFs are not eligible."""
        is_valid, reason = YieldTargetService.validate_cow_for_target(calf.id, tenant_id=1)
        assert is_valid is False
        assert "CALF" in reason

    def test_validate_nonexistent_cow(self, app_context):
        """Test validation of nonexistent cow."""
        is_valid, reason = YieldTargetService.validate_cow_for_target(9999, tenant_id=1)
        assert is_valid is False
        assert "not found" in reason

    def test_set_target_invalid_liters_negative(self, app_context, lactating_cow):
        """Test that negative target_liters are rejected."""
        with pytest.raises(ValueError, match="greater than 0"):
            YieldTargetService.set_yield_target(
                tenant_id=1,
                cow_id=lactating_cow.id,
                target_liters=-1.0,
            )

    def test_set_target_invalid_feed_negative(self, app_context, lactating_cow):
        """Test that negative base_herd_feed_kg is rejected."""
        with pytest.raises(ValueError, match="cannot be negative"):
            YieldTargetService.set_yield_target(
                tenant_id=1,
                cow_id=lactating_cow.id,
                target_liters=2.5,
                base_herd_feed_kg=-0.5,
            )

    def test_set_target_invalid_frequency(self, app_context, lactating_cow):
        """Test that invalid feed frequency is rejected."""
        with pytest.raises(ValueError, match="must be 2, 3, or 4"):
            YieldTargetService.set_yield_target(
                tenant_id=1,
                cow_id=lactating_cow.id,
                target_liters=2.5,
                times_to_feed_daily=5,
            )

    def test_get_yield_target(self, app_context, lactating_cow):
        """Test retrieving yield target."""
        YieldTargetService.set_yield_target(
            tenant_id=1,
            cow_id=lactating_cow.id,
            target_liters=2.5,
        )
        result = YieldTargetService.get_yield_target(tenant_id=1, cow_id=lactating_cow.id)
        assert result is not None
        assert result['cow_id'] == lactating_cow.id
        assert result['target_liters'] == 2.5

    def test_get_nonexistent_target(self, app_context, lactating_cow):
        """Test retrieving nonexistent target returns None."""
        result = YieldTargetService.get_yield_target(tenant_id=1, cow_id=lactating_cow.id)
        assert result is None

    def test_get_all_yield_targets(self, app_context, lactating_cow):
        """Test listing all yield targets."""
        cow2 = Cow(
            tenant_id=1,
            tag_number='LACT-002',
            name='Lactating Cow 2',
            breed_status='Foundation',
            date_of_birth='2020-02-01',
            current_status=CowStatus.LACTATING,
            is_active=True,
        )
        db.session.add(cow2)
        db.session.commit()

        YieldTargetService.set_yield_target(tenant_id=1, cow_id=lactating_cow.id, target_liters=2.5)
        YieldTargetService.set_yield_target(tenant_id=1, cow_id=cow2.id, target_liters=2.0)

        targets = YieldTargetService.get_all_yield_targets(tenant_id=1)
        assert len(targets) == 2

    def test_deactivate_yield_target(self, app_context, lactating_cow):
        """Test deactivating a yield target."""
        YieldTargetService.set_yield_target(tenant_id=1, cow_id=lactating_cow.id, target_liters=2.5)
        result = YieldTargetService.deactivate_yield_target(tenant_id=1, cow_id=lactating_cow.id)
        assert result['status'] == 'Inactive'

    def test_tenant_isolation(self, app_context, lactating_cow):
        """Test that yield targets are isolated by tenant."""
        YieldTargetService.set_yield_target(
            tenant_id=1,
            cow_id=lactating_cow.id,
            target_liters=2.5,
        )
        # Query with different tenant should not find it
        result = YieldTargetService.get_yield_target(tenant_id=2, cow_id=lactating_cow.id)
        assert result is None
