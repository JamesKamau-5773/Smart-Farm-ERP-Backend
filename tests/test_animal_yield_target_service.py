"""
Tests for AnimalYieldTargetService - business logic layer tests.
"""

from datetime import date
from app import db
from app.models.livestock import Cow, AnimalYieldTarget, CowStatus
from app.services.animal_yield_target_service import AnimalYieldTargetService
from tests.base import BaseTestCase


class TestAnimalYieldTargetService(BaseTestCase):
    """Test suite for the AnimalYieldTargetService."""

    def setUp(self):
        """Setup for each test."""
        super().setUp()
        self.lactating_cow = Cow(
            tenant_id=self.tenant.id,
            tag_number='L-001',
            name='Lactating Cow',
            date_of_birth=date(2020, 1, 1),
            current_status=CowStatus.LACTATING,
            is_active=True,
        )
        self.dry_cow = Cow(
            tenant_id=self.tenant.id,
            tag_number='D-001',
            name='Dry Cow',
            date_of_birth=date(2020, 1, 1),
            current_status=CowStatus.DRY,
            is_active=True,
        )
        db.session.add_all([self.lactating_cow, self.dry_cow])
        db.session.commit()

    def test_set_yield_target_success_for_lactating_cow(self):
        """Test setting a yield target for a lactating cow succeeds."""
        result = AnimalYieldTargetService.set_yield_target(
            tenant_id=self.tenant.id,
            cow_id=self.lactating_cow.id,
            target_liters=25.5
        )
        self.assertIn('target_id', result)
        self.assertEqual(result['target_liters'], 25.5)
        self.assertEqual(result['status'], 'Active')
        self.assertTrue(result['is_active'])
        self.assertEqual(len(result['warnings']), 0)

    def test_set_yield_target_for_dry_cow_with_warning(self):
        """Test setting a target for a dry cow succeeds but is inactive and has a warning."""
        result = AnimalYieldTargetService.set_yield_target(
            tenant_id=self.tenant.id,
            cow_id=self.dry_cow.id,
            target_liters=20.0
        )
        self.assertIn('target_id', result)
        self.assertFalse(result['is_active'])
        self.assertGreater(len(result['warnings']), 0)
        self.assertIn('not LACTATING', result['warnings'][0])

    def test_set_yield_target_invalid_liters_fails(self):
        """Test that setting a negative or zero yield target fails."""
        with self.assertRaises(ValueError) as cm:
            AnimalYieldTargetService.set_yield_target(
                tenant_id=self.tenant.id,
                cow_id=self.lactating_cow.id,
                target_liters=-5.0
            )
        self.assertIn('must be greater than 0', str(cm.exception))

    def test_set_yield_target_for_invalid_cow_fails(self):
        """Test that setting a target for a non-existent cow fails."""
        with self.assertRaises(ValueError) as cm:
            AnimalYieldTargetService.set_yield_target(
                tenant_id=self.tenant.id,
                cow_id=9999,
                target_liters=20.0
            )
        self.assertIn('not found', str(cm.exception))

    def test_list_herd_targets_only_includes_active_lactating(self):
        """Test that listing herd targets only includes those for active, lactating cows."""
        # Set targets for both a lactating and a dry cow
        AnimalYieldTargetService.set_yield_target(
            tenant_id=self.tenant.id, cow_id=self.lactating_cow.id, target_liters=25.0
        )
        AnimalYieldTargetService.set_yield_target(
            tenant_id=self.tenant.id, cow_id=self.dry_cow.id, target_liters=20.0
        )

        # The service method should only return targets for active, lactating cows
        targets = AnimalYieldTargetService.list_herd_targets(self.tenant.id)
        
        self.assertEqual(len(targets), 1)
        self.assertEqual(targets[0]['cow_id'], self.lactating_cow.id)

    def test_handle_cow_status_change_deactivates_target(self):
        """Test that changing a cow's status to DRY deactivates its yield target."""
        # Setup: cow is lactating with an active target
        result = AnimalYieldTargetService.set_yield_target(
            tenant_id=self.tenant.id, cow_id=self.lactating_cow.id, target_liters=25.0
        )
        target_id = result['target_id']
        
        # Action: Cow status changes to DRY
        self.lactating_cow.current_status = CowStatus.DRY
        db.session.commit()
        
        AnimalYieldTargetService.handle_cow_status_change(
            cow_id=self.lactating_cow.id,
            new_status=CowStatus.DRY,
            tenant_id=self.tenant.id
        )

        # Assertion: The target should now be inactive
        target = AnimalYieldTarget.query.get(target_id)
        self.assertIsNotNone(target)
        self.assertFalse(target.is_active)
        self.assertEqual(target.status, 'Inactive')
