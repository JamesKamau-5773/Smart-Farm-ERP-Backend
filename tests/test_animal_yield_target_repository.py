"""
Tests for AnimalYieldTargetRepository - data access layer tests.
"""

from datetime import date
from app import db
from app.models.livestock import Cow, AnimalYieldTarget, CowStatus
from app.models.tenant import Tenant
from app.repositories.animal_yield_target_repo import AnimalYieldTargetRepository
from tests.base import BaseTestCase


class TestAnimalYieldTargetRepository(BaseTestCase):
    """Test suite for repository layer."""

    def setUp(self):
        """Setup for each test."""
        super().setUp()
        self.repo = AnimalYieldTargetRepository()
        
        # Create a test cow
        self.cow = Cow(
            tenant_id=self.tenant.id,
            tag_number='C-001',
            name='Daisy',
            breed='Holstein',
            date_of_birth=date(2020, 1, 1),
            current_status=CowStatus.LACTATING,
            is_active=True,
        )
        db.session.add(self.cow)
        db.session.commit()

    def test_create_new_yield_target(self):
        """Test creating a new yield target."""
        # Create yield target
        target = self.repo.create_or_update(
            tenant_id=self.tenant.id,
            cow_id=self.cow.id,
            target_liters=2.5,
            times_to_feed_daily=2
        )

        assert target.id is not None
        assert target.animal_id == self.cow.id
        assert float(target.target_liters) == 2.5
        assert target.times_to_feed_daily == 2
        assert target.status == 'Active'

    def test_update_existing_yield_target(self):
        """Test updating an existing yield target."""
        # Create initial target
        target1 = self.repo.create_or_update(
            tenant_id=self.tenant.id,
            cow_id=self.cow.id,
            target_liters=2.0
        )
        target1_id = target1.id

        # Update target
        target2 = self.repo.create_or_update(
            tenant_id=self.tenant.id,
            cow_id=self.cow.id,
            target_liters=3.0
        )

        assert target2.id == target1_id
        assert float(target2.target_liters) == 3.0

    def test_get_by_cow_id(self):
        """Test retrieving target by cow ID."""
        # Create target
        created_target = self.repo.create_or_update(
            tenant_id=self.tenant.id,
            cow_id=self.cow.id,
            target_liters=2.5
        )

        # Retrieve target
        retrieved_target = self.repo.get_by_cow_id(self.cow.id, self.tenant.id)
        
        assert retrieved_target is not None
        assert retrieved_target.id == created_target.id
        assert float(retrieved_target.target_liters) == 2.5

    def test_get_active_targets_for_herd(self):
        """Test retrieving all active targets for lactating cows."""
        # Create test cows
        cow1 = Cow(
            tenant_id=self.tenant.id,
            tag_number='C-004',
            date_of_birth=date(2020, 1, 1),
            current_status=CowStatus.LACTATING,
            is_active=True
        )
        cow2 = Cow(
            tenant_id=self.tenant.id,
            tag_number='C-005',
            date_of_birth=date(2020, 1, 1),
            current_status=CowStatus.DRY,  # Dry cow
            is_active=True
        )
        db.session.add_all([cow1, cow2])
        db.session.commit()

        # Create targets
        self.repo.create_or_update(
            tenant_id=self.tenant.id,
            cow_id=self.cow.id,
            target_liters=2.5
        )
        self.repo.create_or_update(
            tenant_id=self.tenant.id,
            cow_id=cow1.id,
            target_liters=2.0
        )
        self.repo.create_or_update(
            tenant_id=self.tenant.id,
            cow_id=cow2.id,
            target_liters=1.5
        )

        # Get active targets (should only get lactating cows)
        active_targets = self.repo.get_active_targets_for_herd(self.tenant.id)
        
        assert len(active_targets) == 2  # Only LACTATING cows
        active_cow_ids = [t.animal_id for t in active_targets]
        assert self.cow.id in active_cow_ids
        assert cow1.id in active_cow_ids
        assert cow2.id not in active_cow_ids  # DRY cow excluded

    def test_deactivate_target(self):
        """Test deactivating a yield target."""
        target = self.repo.create_or_update(
            tenant_id=self.tenant.id,
            cow_id=self.cow.id,
            target_liters=2.5
        )

        # Deactivate
        success = self.repo.deactivate(target.id, self.tenant.id)
        assert success is True
        
        # Verify deactivation
        deactivated = self.repo.get_by_id(target.id, self.tenant.id)
        assert deactivated.status == 'Inactive'

    def test_delete_target(self):
        """Test deleting a yield target."""
        target = self.repo.create_or_update(
            tenant_id=self.tenant.id,
            cow_id=self.cow.id,
            target_liters=2.5
        )
        target_id = target.id

        # Delete
        success = self.repo.delete(target_id, self.tenant.id)
        assert success is True
        
        # Verify deletion
        deleted = self.repo.get_by_id(target_id, self.tenant.id)
        assert deleted is None

    def test_tenant_isolation(self):
        """Test that yield targets are properly isolated by tenant."""
        # Create another tenant
        other_tenant = Tenant(name='Other Tenant', tenant_type='single')
        db.session.add(other_tenant)
        db.session.commit()

        # Create target for first tenant
        target1 = self.repo.create_or_update(
            tenant_id=self.tenant.id,
            cow_id=self.cow.id,
            target_liters=2.5
        )

        # Verify tenant isolation
        retrieved_for_other = self.repo.get_by_id(target1.id, other_tenant.id)
        assert retrieved_for_other is None

    def test_create_target_with_invalid_cow(self):
        """Test that creating target with non-existent cow fails."""
        target = self.repo.create_or_update(
            tenant_id=self.tenant.id,
            cow_id=9999,  # Non-existent
            target_liters=2.5
        )
        assert target is None

