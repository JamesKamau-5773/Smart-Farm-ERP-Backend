"""
Tests for AnimalYieldTargetService - business logic layer tests.
"""

import unittest
from datetime import date
from decimal import Decimal

from app import db
from app.models.livestock import Cow, CowStatus
from app.services.animal_yield_target_service import AnimalYieldTargetService
from tests.base import BaseTestCase


class TestAnimalYieldTargetService(BaseTestCase):
    """Test suite for service layer business logic."""

    def test_set_yield_target_success(self):
        """Test successfully setting a yield target."""
        # Create test cow
        cow = Cow(
            tenant_id=self.tenant.id,
            tag_number='C-TEST-001',
            name='TestCow',
            date_of_birth=date(2020, 1, 1),
            current_status=CowStatus.LACTATING
        )
        db.session.add(cow)
        db.session.commit()

        # Set yield target
        result = AnimalYieldTargetService.set_yield_target(
            tenant_id=self.tenant.id,
            cow_id=cow.id,
            target_liters=2.5
        )

        self.assertIsNotNone(result['target_id'])
        self.assertEqual(result['cow_id'], cow.id)
        self.assertEqual(result['tag_number'], 'C-TEST-001')
        self.assertEqual(result['target_liters'], 2.5)
        self.assertEqual(result['status'], 'Active')
        self.assertEqual(len(result['warnings']), 0)

    def test_set_yield_target_with_dry_cow_warning(self):
        """Test setting target for dry cow generates warning."""
        # Create dry cow
        cow = Cow(
            tenant_id=self.tenant.id,
            tag_number='C-DRY-001',
            date_of_birth=date(2020, 1, 1),
            current_status=CowStatus.DRY
        )
        db.session.add(cow)
        db.session.commit()

        # Set yield target
        result = AnimalYieldTargetService.set_yield_target(
            tenant_id=self.tenant.id,
            cow_id=cow.id,
            target_liters=2.0,
            validate_status=True
        )

        self.assertEqual(len(result['warnings']), 1)
        self.assertIn('DRY', result['warnings'][0])

    def test_set_yield_target_invalid_liters(self):
        """Test setting target with invalid liters raises error."""
        cow = Cow(
            tenant_id=self.tenant.id,
            tag_number='C-TEST-002',
            date_of_birth=date(2020, 1, 1),
            current_status=CowStatus.LACTATING
        )
        db.session.add(cow)
        db.session.commit()

        # Test negative liters
        with self.assertRaisesRegex(ValueError, 'must be greater than 0'):
            AnimalYieldTargetService.set_yield_target(
                tenant_id=self.tenant.id,
                cow_id=cow.id,
                target_liters=-1.0
            )

        # Test non-numeric liters
        with self.assertRaisesRegex(ValueError, 'must be a valid number'):
            AnimalYieldTargetService.set_yield_target(
                tenant_id=self.tenant.id,
                cow_id=cow.id,
                target_liters='invalid'
            )

    def test_set_yield_target_nonexistent_cow(self):
        """Test setting target for non-existent cow raises error."""
        with self.assertRaisesRegex(ValueError, 'not found'):
            AnimalYieldTargetService.set_yield_target(
                tenant_id=self.tenant.id,
                cow_id=9999,
                target_liters=2.5
            )

    def test_get_cow_target(self):
        """Test retrieving cow target."""
        # Create cow and target
        cow = Cow(
            tenant_id=self.tenant.id,
            tag_number='C-TEST-003',
            name='Bessie',
            date_of_birth=date(2020, 1, 1),
            current_status=CowStatus.LACTATING
        )
        db.session.add(cow)
        db.session.commit()

        AnimalYieldTargetService.set_yield_target(
            tenant_id=self.tenant.id,
            cow_id=cow.id,
            target_liters=2.8
        )

        # Get target
        result = AnimalYieldTargetService.get_cow_target(tenant_id=self.tenant.id, cow_id=cow.id)

        self.assertIsNotNone(result)
        self.assertEqual(result['cow_id'], cow.id)
        self.assertEqual(result['tag_number'], 'C-TEST-003')
        self.assertEqual(result['target_liters'], 2.8)
        self.assertEqual(result['status'], 'Active')

    def test_get_cow_target_not_found(self):
        """Test getting target for cow without target returns None."""
        cow = Cow(
            tenant_id=self.tenant.id,
            tag_number='C-TEST-004',
            date_of_birth=date(2020, 1, 1),
            current_status=CowStatus.LACTATING
        )
        db.session.add(cow)
        db.session.commit()

        result = AnimalYieldTargetService.get_cow_target(tenant_id=self.tenant.id, cow_id=cow.id)
        self.assertIsNone(result)

    def test_list_herd_targets(self):
        """Test listing all herd yield targets."""
        # Create multiple cows with targets
        cows_data = [
            ('C-001', 'Daisy', 2.5),
            ('C-002', 'Bessie', 3.0),
            ('C-003', 'Ruby', 2.2),
        ]

        for tag, name, liters in cows_data:
            cow = Cow(
                tenant_id=self.tenant.id,
                tag_number=tag,
                name=name,
                date_of_birth=date(2020, 1, 1),
                current_status=CowStatus.LACTATING,
                is_active=True
            )
            db.session.add(cow)
            db.session.commit()

            AnimalYieldTargetService.set_yield_target(
                tenant_id=self.tenant.id,
                cow_id=cow.id,
                target_liters=liters
            )

        # List targets
        targets = AnimalYieldTargetService.list_herd_targets(tenant_id=self.tenant.id)

        self.assertEqual(len(targets), 3)
        self.assertTrue(all(t['status'] == 'Active' for t in targets))
        self.assertEqual(set(t['tag_number'] for t in targets), {'C-001', 'C-002', 'C-003'})

    def test_calculate_herd_feeding_plan(self):
        """Test calculating aggregated feeding plan."""
        # Create cows with targets
        cows_data = [
            ('C-F-001', 'Daisy', 2.5),
            ('C-F-002', 'Bessie', 1.8),
        ]

        for tag, name, liters in cows_data:
            cow = Cow(
                tenant_id=self.tenant.id,
                tag_number=tag,
                name=name,
                date_of_birth=date(2020, 1, 1),
                current_status=CowStatus.LACTATING,
                is_active=True
            )
            db.session.add(cow)
            db.session.commit()

            AnimalYieldTargetService.set_yield_target(
                tenant_id=self.tenant.id,
                cow_id=cow.id,
                target_liters=liters
            )

        # Calculate feeding plan
        plan = AnimalYieldTargetService.calculate_herd_feeding_plan(
            tenant_id=self.tenant.id,
            baseline_herd_meal_kg=4.0,
            use_saved_targets=True
        )

        # Verify plan structure
        self.assertEqual(plan['total_herd_target_liters'], 4.3)  # 2.5 + 1.8
        self.assertEqual(plan['number_of_cows'], 2)
        self.assertEqual(len(plan['per_cow_breakdown']), 2)
        self.assertIn('total_meal_needed_kg', plan)
        self.assertIn('suggested_yard_feedings', plan)
        self.assertIn('farmer_reasoning', plan)

        # Verify per-cow breakdown
        daisy_breakdown = next(b for b in plan['per_cow_breakdown'] if b['tag'] == 'C-F-001')
        self.assertEqual(daisy_breakdown['target_liters'], 2.5)
        self.assertGreater(daisy_breakdown['feed_allocation_kg'], 0)
        self.assertGreaterEqual(daisy_breakdown['topup_kg'], 0)

    def test_calculate_herd_feeding_plan_no_targets(self):
        """Test calculating plan with no targets raises error."""
        with self.assertRaisesRegex(ValueError, 'No active yield targets found'):
            AnimalYieldTargetService.calculate_herd_feeding_plan(
                tenant_id=self.tenant.id,
                use_saved_targets=True
            )

    def test_calculate_herd_feeding_plan_with_frequency_override(self):
        """Test calculating plan with explicit milking frequency."""
        # Create cow with target
        cow = Cow(
            tenant_id=self.tenant.id,
            tag_number='C-FREQ-001',
            date_of_birth=date(2020, 1, 1),
            current_status=CowStatus.LACTATING,
            is_active=True
        )
        db.session.add(cow)
        db.session.commit()

        AnimalYieldTargetService.set_yield_target(
            tenant_id=self.tenant.id,
            cow_id=cow.id,
            target_liters=3.0
        )

        # Calculate with frequency override
        plan = AnimalYieldTargetService.calculate_herd_feeding_plan(
            tenant_id=self.tenant.id,
            milking_frequency=3  # Override to 3 times daily
        )

        self.assertEqual(plan['used_milking_frequency'], 3)

    def test_deactivate_target(self):
        """Test deactivating a yield target."""
        # Create cow and target
        cow = Cow(
            tenant_id=self.tenant.id,
            tag_number='C-DEACT-001',
            date_of_birth=date(2020, 1, 1),
            current_status=CowStatus.LACTATING
        )
        db.session.add(cow)
        db.session.commit()

        result = AnimalYieldTargetService.set_yield_target(
            tenant_id=self.tenant.id,
            cow_id=cow.id,
            target_liters=2.5
        )
        target_id = result['target_id']

        # Deactivate
        deactivate_result = AnimalYieldTargetService.deactivate_target(
            tenant_id=self.tenant.id,
            target_id=target_id
        )

        self.assertIn('message', deactivate_result)

        # Verify deactivation
        retrieved = AnimalYieldTargetService.get_cow_target(tenant_id=self.tenant.id, cow_id=cow.id)
        self.assertEqual(retrieved['status'], 'Inactive')

    def test_delete_target(self):
        """Test deleting a yield target."""
        # Create cow and target
        cow = Cow(
            tenant_id=self.tenant.id,
            tag_number='C-DEL-001',
            date_of_birth=date(2020, 1, 1),
            current_status=CowStatus.LACTATING
        )
        db.session.add(cow)
        db.session.commit()

        result = AnimalYieldTargetService.set_yield_target(
            tenant_id=self.tenant.id,
            cow_id=cow.id,
            target_liters=2.5
        )
        target_id = result['target_id']

        # Delete
        delete_result = AnimalYieldTargetService.delete_target(
            tenant_id=self.tenant.id,
            target_id=target_id
        )

        self.assertIn('message', delete_result)

        # Verify deletion
        retrieved = AnimalYieldTargetService.get_cow_target(tenant_id=self.tenant.id, cow_id=cow.id)
        self.assertIsNone(retrieved)

    def test_handle_cow_status_change_to_dry(self):
        """Test that cow status change to DRY deactivates target."""
        # Create cow and target
        cow = Cow(
            tenant_id=self.tenant.id,
            tag_number='C-STATUS-001',
            date_of_birth=date(2020, 1, 1),
            current_status=CowStatus.LACTATING
        )
        db.session.add(cow)
        db.session.commit()

        result = AnimalYieldTargetService.set_yield_target(
            tenant_id=self.tenant.id,
            cow_id=cow.id,
            target_liters=2.5
        )

        # Change cow status to DRY
        AnimalYieldTargetService.handle_cow_status_change(
            cow_id=cow.id,
            new_status=CowStatus.DRY,
            tenant_id=self.tenant.id
        )

        # Verify target is deactivated
        retrieved = AnimalYieldTargetService.get_cow_target(tenant_id=self.tenant.id, cow_id=cow.id)
        self.assertEqual(retrieved['status'], 'Inactive')

    def test_per_cow_breakdown_proportional_allocation(self):
        """Test that per-cow feed allocation is proportional to milk targets."""
        # Create cows with specific target ratios
        # Cow 1: 3.0 liters (60% of total)
        # Cow 2: 2.0 liters (40% of total)
        cows_data = [
            ('C-PROP-001', 'Daisy', 3.0),
            ('C-PROP-002', 'Bessie', 2.0),
        ]

        for tag, name, liters in cows_data:
            cow = Cow(
                tenant_id=self.tenant.id,
                tag_number=tag,
                name=name,
                date_of_birth=date(2020, 1, 1),
                current_status=CowStatus.LACTATING,
                is_active=True
            )
            db.session.add(cow)
            db.session.commit()

            AnimalYieldTargetService.set_yield_target(
                tenant_id=self.tenant.id,
                cow_id=cow.id,
                target_liters=liters
            )

        # Calculate plan
        plan = AnimalYieldTargetService.calculate_herd_feeding_plan(
            tenant_id=self.tenant.id
        )

        # Get breakdown
        daisy = next(b for b in plan['per_cow_breakdown'] if b['tag'] == 'C-PROP-001')
        bessie = next(b for b in plan['per_cow_breakdown'] if b['tag'] == 'C-PROP-002')

        # Daisy gets 60%, Bessie gets 40%
        total_feed = daisy['feed_allocation_kg'] + bessie['feed_allocation_kg']
        daisy_proportion = daisy['feed_allocation_kg'] / total_feed
        bessie_proportion = bessie['feed_allocation_kg'] / total_feed

        # Check proportions (allowing small floating point variance)
        self.assertLess(abs(daisy_proportion - 0.6), 0.01)
        self.assertLess(abs(bessie_proportion - 0.4), 0.01)
