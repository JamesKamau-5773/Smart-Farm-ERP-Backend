"""
Tests for YieldTargetRepository - Data Access Layer
Tests: CRUD operations, filtering, and constraint violations
"""
import pytest
from app.models.livestock import AnimalYieldTarget, Cow, CowStatus
from app.repositories.yield_target_repo import YieldTargetRepository
from app import db


@pytest.fixture
def sample_cow(tenant_id=1):
    """Create a sample cow for testing."""
    cow = Cow(
        tenant_id=tenant_id,
        tag_number='TEST-001',
        name='Test Cow',
        breed_status='Foundation',
        date_of_birth='2020-01-01',
        current_status=CowStatus.LACTATING,
        is_active=True,
    )
    db.session.add(cow)
    db.session.commit()
    return cow


class TestYieldTargetRepository:
    """Repository tests for YieldTargetRepository."""

    def test_create_yield_target(self, app_context, sample_cow):
        """Test creating a new yield target."""
        target = YieldTargetRepository.create(
            tenant_id=1,
            animal_id=sample_cow.id,
            target_liters=2.5,
            base_herd_feed_kg=0.5,
            times_to_feed_daily=2,
        )
        assert target.id is not None
        assert target.animal_id == sample_cow.id
        assert float(target.target_liters) == 2.5
        assert target.status == 'Active'

    def test_get_by_animal_id(self, app_context, sample_cow):
        """Test retrieving yield target by cow ID."""
        created = YieldTargetRepository.create(
            tenant_id=1,
            animal_id=sample_cow.id,
            target_liters=3.0,
        )
        retrieved = YieldTargetRepository.get_by_animal_id(sample_cow.id, tenant_id=1)
        assert retrieved.id == created.id
        assert float(retrieved.target_liters) == 3.0

    def test_create_duplicate_target_raises_error(self, app_context, sample_cow):
        """Test that duplicate targets for same cow are rejected."""
        YieldTargetRepository.create(
            tenant_id=1,
            animal_id=sample_cow.id,
            target_liters=2.5,
        )
        with pytest.raises(ValueError, match="already exists"):
            YieldTargetRepository.create(
                tenant_id=1,
                animal_id=sample_cow.id,
                target_liters=3.0,
            )

    def test_create_nonexistent_cow_raises_error(self, app_context):
        """Test that creating target for nonexistent cow raises error."""
        with pytest.raises(ValueError, match="not found"):
            YieldTargetRepository.create(
                tenant_id=1,
                animal_id=9999,
                target_liters=2.5,
            )

    def test_update_yield_target(self, app_context, sample_cow):
        """Test updating yield target fields."""
        target = YieldTargetRepository.create(
            tenant_id=1,
            animal_id=sample_cow.id,
            target_liters=2.5,
            times_to_feed_daily=2,
        )
        updated = YieldTargetRepository.update(
            target.id,
            tenant_id=1,
            target_liters=3.5,
            times_to_feed_daily=3,
        )
        assert float(updated.target_liters) == 3.5
        assert updated.times_to_feed_daily == 3

    def test_deactivate_yield_target(self, app_context, sample_cow):
        """Test deactivating a yield target."""
        target = YieldTargetRepository.create(
            tenant_id=1,
            animal_id=sample_cow.id,
            target_liters=2.5,
        )
        deactivated = YieldTargetRepository.deactivate(target.id, tenant_id=1)
        assert deactivated.status == 'Inactive'

    def test_get_all_active(self, app_context, sample_cow):
        """Test retrieving all active yield targets."""
        cow2 = Cow(
            tenant_id=1,
            tag_number='TEST-002',
            name='Test Cow 2',
            breed_status='Foundation',
            date_of_birth='2020-02-01',
            current_status=CowStatus.LACTATING,
            is_active=True,
        )
        db.session.add(cow2)
        db.session.commit()

        target1 = YieldTargetRepository.create(
            tenant_id=1,
            animal_id=sample_cow.id,
            target_liters=2.5,
        )
        target2 = YieldTargetRepository.create(
            tenant_id=1,
            animal_id=cow2.id,
            target_liters=2.0,
        )
        targets = YieldTargetRepository.get_all_active(tenant_id=1)
        assert len(targets) == 2
        assert {t.id for t in targets} == {target1.id, target2.id}

    def test_tenant_isolation(self, app_context, sample_cow):
        """Test that yield targets are isolated by tenant."""
        target = YieldTargetRepository.create(
            tenant_id=1,
            animal_id=sample_cow.id,
            target_liters=2.5,
        )
        # Query with different tenant should not find the target
        retrieved = YieldTargetRepository.get_by_id(target.id, tenant_id=2)
        assert retrieved is None
