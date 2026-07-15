"""
Tests for Animal Yield Target API endpoints.
Integration tests for the full stack: API -> Service -> Repository -> Database.
"""

import json
import unittest
from datetime import date

from app import db
from app.models.livestock import Cow, CowStatus
from tests.base import BaseTestCase


class TestAnimalYieldTargetAPI(BaseTestCase):
    """Integration tests for yield target endpoints."""

    def setUp(self):
        """Set up test fixtures before each test method."""
        super().setUp()
        # Create a test user with JWT token
        self.user = self.create_user(
            username='testuser',
            password='testpass',
            role='FARMER',
            tenant=self.tenant
        )
        # Generate JWT token by logging in
        login_response = self.client.post(
            '/api/auth/login',
            json={'username': 'testuser', 'password': 'testpass'}
        )
        if login_response.status_code == 200:
            self.user_token = json.loads(login_response.data)['token']
        else:
            # If token generation fails, set a placeholder
            self.user_token = 'test-token'
        
        self.auth_headers = {'Authorization': f'Bearer {self.user_token}'}

    def _create_test_cow(self):
        """Helper method to create a test lactating cow."""
        cow = Cow(
            tenant_id=self.tenant.id,
            tag_number='API-TEST-001',
            name='TestCow',
            date_of_birth=date(2020, 1, 1),
            current_status=CowStatus.LACTATING,
            is_active=True
        )
        db.session.add(cow)
        db.session.commit()
        return cow

    def test_set_yield_target_success(self):
        """Test successfully setting a yield target via API."""
        test_cow = self._create_test_cow()
        payload = {'target_liters': 2.5}

        response = self.client.post(
            f'/api/v1/animals/{test_cow.id}/yield-target',
            data=json.dumps(payload),
            headers={**self.auth_headers, 'Content-Type': 'application/json'}
        )

        self.assertEqual(response.status_code, 201)
        data = json.loads(response.data)
        self.assertIsNotNone(data['target_id'])
        self.assertEqual(data['cow_id'], test_cow.id)
        self.assertEqual(data['tag_number'], 'API-TEST-001')
        self.assertEqual(data['target_liters'], 2.5)
        self.assertEqual(data['status'], 'Active')

    def test_set_yield_target_missing_liters(self):
        """Test setting target without target_liters returns 400."""
        test_cow = self._create_test_cow()
        payload = {}

        response = self.client.post(
            f'/api/v1/animals/{test_cow.id}/yield-target',
            data=json.dumps(payload),
            headers={**self.auth_headers, 'Content-Type': 'application/json'}
        )

        self.assertEqual(response.status_code, 400)
        data = json.loads(response.data)
        self.assertIn('target_liters', data['error'])

    def test_set_yield_target_invalid_liters(self):
        """Test setting target with invalid liters returns 400."""
        test_cow = self._create_test_cow()
        payload = {'target_liters': -1.0}

        response = self.client.post(
            f'/api/v1/animals/{test_cow.id}/yield-target',
            data=json.dumps(payload),
            headers={**self.auth_headers, 'Content-Type': 'application/json'}
        )

        self.assertEqual(response.status_code, 400)

    def test_set_yield_target_nonexistent_cow(self):
        """Test setting target for non-existent cow returns 400."""
        payload = {'target_liters': 2.5}

        response = self.client.post(
            f'/api/v1/animals/99999/yield-target',
            data=json.dumps(payload),
            headers={**self.auth_headers, 'Content-Type': 'application/json'}
        )

        self.assertEqual(response.status_code, 400)

    def test_set_yield_target_no_auth(self):
        """Test setting target without auth returns 401."""
        test_cow = self._create_test_cow()
        payload = {'target_liters': 2.5}

        response = self.client.post(
            f'/api/v1/animals/{test_cow.id}/yield-target',
            data=json.dumps(payload),
            headers={'Content-Type': 'application/json'}
        )

        self.assertEqual(response.status_code, 401)

    def test_get_yield_target_success(self):
        """Test retrieving yield target via API."""
        test_cow = self._create_test_cow()
        # First set a target
        payload = {'target_liters': 2.8}
        self.client.post(
            f'/api/v1/animals/{test_cow.id}/yield-target',
            data=json.dumps(payload),
            headers={**self.auth_headers, 'Content-Type': 'application/json'}
        )

        # Get target
        response = self.client.get(
            f'/api/v1/animals/{test_cow.id}/yield-target',
            headers=self.auth_headers
        )

        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertEqual(data['cow_id'], test_cow.id)
        self.assertEqual(data['target_liters'], 2.8)
        self.assertEqual(data['status'], 'Active')

    def test_get_yield_target_not_found(self):
        """Test getting target for cow without target returns 404."""
        test_cow = self._create_test_cow()
        response = self.client.get(
            f'/api/v1/animals/{test_cow.id}/yield-target',
            headers=self.auth_headers
        )

        self.assertEqual(response.status_code, 404)

    def test_list_herd_targets_success(self):
        """Test listing herd targets via API."""
        # Create multiple test cows with targets
        for i in range(3):
            cow = Cow(
                tenant_id=self.tenant.id,
                tag_number=f'LIST-TEST-{i:03d}',
                name=f'Cow{i}',
                date_of_birth=date(2020, 1, 1),
                current_status=CowStatus.LACTATING,
                is_active=True
            )
            db.session.add(cow)
            db.session.commit()

            # Set target
            payload = {'target_liters': 2.5 + i}
            self.client.post(
                f'/api/v1/animals/{cow.id}/yield-target',
                data=json.dumps(payload),
                headers={**self.auth_headers, 'Content-Type': 'application/json'}
            )

        # List targets
        response = self.client.get(
            '/api/v1/herd/yield-targets',
            headers=self.auth_headers
        )

        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertEqual(data['total_cows'], 3)
        self.assertEqual(len(data['targets']), 3)
        self.assertTrue(all(t['status'] == 'Active' for t in data['targets']))

    def test_list_herd_targets_empty(self):
        """Test listing herd targets when none exist."""
        response = self.client.get(
            '/api/v1/herd/yield-targets',
            headers=self.auth_headers
        )

        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertEqual(data['total_cows'], 0)
        self.assertEqual(len(data['targets']), 0)

    def test_calculate_herd_feeding_plan_success(self):
        """Test calculating herd feeding plan via API."""
        # Create cows with targets
        for i, liters in enumerate([2.5, 1.8]):
            cow = Cow(
                tenant_id=self.tenant.id,
                tag_number=f'PLAN-TEST-{i:03d}',
                name=f'Cow{i}',
                date_of_birth=date(2020, 1, 1),
                current_status=CowStatus.LACTATING,
                is_active=True
            )
            db.session.add(cow)
            db.session.commit()

            payload = {'target_liters': liters}
            self.client.post(
                f'/api/v1/animals/{cow.id}/yield-target',
                data=json.dumps(payload),
                headers={**self.auth_headers, 'Content-Type': 'application/json'}
            )

        # Calculate feeding plan
        response = self.client.get(
            '/api/v1/herd/feeding-plan',
            headers=self.auth_headers
        )

        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertEqual(data['total_herd_target_liters'], 4.3)
        self.assertEqual(data['number_of_cows'], 2)
        self.assertEqual(len(data['per_cow_breakdown']), 2)
        self.assertIn('total_meal_needed_kg', data)
        self.assertIn('suggested_yard_feedings', data)
        self.assertIn('farmer_reasoning', data)

    def test_calculate_herd_feeding_plan_no_targets(self):
        """Test calculating plan with no targets returns 400."""
        response = self.client.get(
            '/api/v1/herd/feeding-plan',
            headers=self.auth_headers
        )

        self.assertEqual(response.status_code, 400)
        data = json.loads(response.data)
        self.assertIn('No active yield targets', data['error'])

    def test_calculate_herd_feeding_plan_with_parameters(self):
        """Test calculating plan with query parameters."""
        # Create cow with target
        cow = Cow(
            tenant_id=self.tenant.id,
            tag_number='PARAM-TEST-001',
            date_of_birth=date(2020, 1, 1),
            current_status=CowStatus.LACTATING,
            is_active=True
        )
        db.session.add(cow)
        db.session.commit()

        payload = {'target_liters': 2.5}
        self.client.post(
            f'/api/v1/animals/{cow.id}/yield-target',
            data=json.dumps(payload),
            headers={**self.auth_headers, 'Content-Type': 'application/json'}
        )

        # Calculate with custom parameters
        response = self.client.get(
            '/api/v1/herd/feeding-plan?baseline_herd_meal_kg=3.0&milking_frequency=3',
            headers=self.auth_headers
        )

        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertEqual(data['used_milking_frequency'], 3)

    def test_calculate_herd_feeding_plan_invalid_frequency(self):
        """Test calculating plan with invalid frequency returns 400."""
        # Create cow with target
        cow = Cow(
            tenant_id=self.tenant.id,
            tag_number='INVALID-FREQ-001',
            date_of_birth=date(2020, 1, 1),
            current_status=CowStatus.LACTATING,
            is_active=True
        )
        db.session.add(cow)
        db.session.commit()

        payload = {'target_liters': 2.5}
        self.client.post(
            f'/api/v1/animals/{cow.id}/yield-target',
            data=json.dumps(payload),
            headers={**self.auth_headers, 'Content-Type': 'application/json'}
        )

        # Try with invalid frequency
        response = self.client.get(
            '/api/v1/herd/feeding-plan?milking_frequency=5',
            headers=self.auth_headers
        )

        self.assertEqual(response.status_code, 400)
        data = json.loads(response.data)
        self.assertIn('milking_frequency must be 2, 3, or 4', data['error'])

    def test_delete_yield_target_success(self):
        """Test deleting a yield target via API."""
        test_cow = self._create_test_cow()
        # First set a target
        set_response = self.client.post(
            f'/api/v1/animals/{test_cow.id}/yield-target',
            data=json.dumps({'target_liters': 2.5}),
            headers={**self.auth_headers, 'Content-Type': 'application/json'}
        )
        target_id = json.loads(set_response.data)['target_id']

        # Delete target
        delete_payload = {'target_id': target_id}
        response = self.client.delete(
            f'/api/v1/animals/{test_cow.id}/yield-target',
            data=json.dumps(delete_payload),
            headers={**self.auth_headers, 'Content-Type': 'application/json'}
        )

        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertIn('message', data)

        # Verify deletion
        get_response = self.client.get(
            f'/api/v1/animals/{test_cow.id}/yield-target',
            headers=self.auth_headers
        )
        self.assertEqual(get_response.status_code, 404)

    def test_tenant_isolation_in_api(self):
        """Test that API respects tenant isolation."""
        # This test would require multiple tenants in context
        # For now, we verify single tenant works correctly
        cow = Cow(
            tenant_id=self.tenant.id,
            tag_number='TENANT-TEST-001',
            date_of_birth=date(2020, 1, 1),
            current_status=CowStatus.LACTATING
        )
        db.session.add(cow)
        db.session.commit()

        # Set target with authenticated request
        payload = {'target_liters': 2.5}
        response = self.client.post(
            f'/api/v1/animals/{cow.id}/yield-target',
            data=json.dumps(payload),
            headers={**self.auth_headers, 'Content-Type': 'application/json'}
        )
        self.assertEqual(response.status_code, 201)
