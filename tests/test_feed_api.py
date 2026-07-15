"""
Tests for Feed API Endpoints
Tests: HTTP contracts, authentication, and error handling
"""
import pytest
from app.models.livestock import Cow, CowStatus
from app import db


@pytest.fixture
def sample_cow_for_api(client, auth_token):
    """Create a cow for API testing."""
    cow = Cow(
        tenant_id=1,
        tag_number='API-TEST-001',
        name='API Test Cow',
        breed_status='Foundation',
        date_of_birth='2020-01-01',
        current_status=CowStatus.LACTATING,
        is_active=True,
    )
    db.session.add(cow)
    db.session.commit()
    return cow


class TestFeedAPIYieldTargets:
    """Tests for yield target API endpoints."""

    def test_post_yield_target_creates_target(self, client, auth_token, sample_cow_for_api):
        """Test creating yield target via POST."""
        response = client.post(
            f'/api/v1/animals/{sample_cow_for_api.id}/yield-target',
            json={
                'target_liters': 2.5,
                'base_herd_feed_kg': 0.5,
                'times_to_feed_daily': 2,
            },
            headers={'Authorization': f'Bearer {auth_token}'},
        )
        assert response.status_code == 201
        data = response.get_json()
        assert data['action'] == 'created'
        assert data['target_liters'] == 2.5
        assert data['cow_id'] == sample_cow_for_api.id

    def test_post_yield_target_missing_token(self, client, sample_cow_for_api):
        """Test that missing token returns 401."""
        response = client.post(
            f'/api/v1/animals/{sample_cow_for_api.id}/yield-target',
            json={'target_liters': 2.5},
        )
        assert response.status_code == 401

    def test_post_yield_target_missing_liters(self, client, auth_token, sample_cow_for_api):
        """Test that missing target_liters returns 400."""
        response = client.post(
            f'/api/v1/animals/{sample_cow_for_api.id}/yield-target',
            json={'base_herd_feed_kg': 0.5},
            headers={'Authorization': f'Bearer {auth_token}'},
        )
        assert response.status_code == 400
        assert 'target_liters' in response.get_json()['error']

    def test_post_yield_target_invalid_cow(self, client, auth_token):
        """Test that invalid cow_id returns 400."""
        response = client.post(
            '/api/v1/animals/9999/yield-target',
            json={'target_liters': 2.5},
            headers={'Authorization': f'Bearer {auth_token}'},
        )
        assert response.status_code == 400

    def test_get_yield_target(self, client, auth_token, sample_cow_for_api):
        """Test retrieving yield target via GET."""
        # Create first
        client.post(
            f'/api/v1/animals/{sample_cow_for_api.id}/yield-target',
            json={'target_liters': 2.5},
            headers={'Authorization': f'Bearer {auth_token}'},
        )
        # Retrieve
        response = client.get(
            f'/api/v1/animals/{sample_cow_for_api.id}/yield-target',
            headers={'Authorization': f'Bearer {auth_token}'},
        )
        assert response.status_code == 200
        data = response.get_json()
        assert data['target_liters'] == 2.5
        assert data['cow_id'] == sample_cow_for_api.id

    def test_get_yield_target_non_v1_alias(self, client, auth_token, sample_cow_for_api):
        """Test retrieving yield target via frontend alias path."""
        client.post(
            f'/api/v1/animals/{sample_cow_for_api.id}/yield-target',
            json={'target_liters': 2.5},
            headers={'Authorization': f'Bearer {auth_token}'},
        )

        response = client.get(
            f'/api/animals/{sample_cow_for_api.id}/yield-target',
            headers={'Authorization': f'Bearer {auth_token}'},
        )
        assert response.status_code == 200
        data = response.get_json()
        assert data['target_liters'] == 2.5
        assert data['cow_id'] == sample_cow_for_api.id

    def test_get_nonexistent_yield_target(self, client, auth_token, sample_cow_for_api):
        """Test retrieving nonexistent target returns 404."""
        response = client.get(
            f'/api/v1/animals/{sample_cow_for_api.id}/yield-target',
            headers={'Authorization': f'Bearer {auth_token}'},
        )
        assert response.status_code == 404

    def test_list_yield_targets(self, client, auth_token):
        """Test listing all yield targets."""
        # Create multiple cows and targets
        cows = []
        for i in range(3):
            cow = Cow(
                tenant_id=1,
                tag_number=f'LIST-{i:03d}',
                name=f'List Test {i}',
                breed_status='Foundation',
                date_of_birth='2020-01-01',
                current_status=CowStatus.LACTATING,
                is_active=True,
            )
            db.session.add(cow)
            cows.append(cow)
        db.session.commit()

        for i, cow in enumerate(cows):
            client.post(
                f'/api/v1/animals/{cow.id}/yield-target',
                json={'target_liters': 2.0 + i * 0.5},
                headers={'Authorization': f'Bearer {auth_token}'},
            )

        response = client.get(
            '/api/v1/herd/yield-targets',
            headers={'Authorization': f'Bearer {auth_token}'},
        )
        assert response.status_code == 200
        data = response.get_json()
        assert data['count'] == 3

    def test_list_yield_targets_non_v1_alias(self, client, auth_token):
        """Test listing all yield targets via frontend alias path."""
        response = client.get(
            '/api/herd/yield-targets',
            headers={'Authorization': f'Bearer {auth_token}'},
        )
        assert response.status_code == 200

    def test_patch_yield_target(self, client, auth_token, sample_cow_for_api):
        """Test updating yield target via PATCH."""
        # Create first
        client.post(
            f'/api/v1/animals/{sample_cow_for_api.id}/yield-target',
            json={'target_liters': 2.5},
            headers={'Authorization': f'Bearer {auth_token}'},
        )
        # Update
        response = client.patch(
            f'/api/v1/animals/{sample_cow_for_api.id}/yield-target',
            json={'target_liters': 3.5},
            headers={'Authorization': f'Bearer {auth_token}'},
        )
        assert response.status_code == 200
        data = response.get_json()
        assert data['target_liters'] == 3.5

    def test_delete_yield_target(self, client, auth_token, sample_cow_for_api):
        """Test deactivating yield target via DELETE."""
        # Create first
        client.post(
            f'/api/v1/animals/{sample_cow_for_api.id}/yield-target',
            json={'target_liters': 2.5},
            headers={'Authorization': f'Bearer {auth_token}'},
        )
        # Delete
        response = client.delete(
            f'/api/v1/animals/{sample_cow_for_api.id}/yield-target',
            headers={'Authorization': f'Bearer {auth_token}'},
        )
        assert response.status_code == 200
        data = response.get_json()
        assert data['status'] == 'Inactive'


class TestFeedAPIHerdPlans:
    """Tests for herd feeding plan API endpoints."""

    def test_get_herd_plan_from_targets_saved(self, client, auth_token):
        """Test calculating herd plan from saved targets."""
        # Create cows with targets
        cows = []
        for i in range(2):
            cow = Cow(
                tenant_id=1,
                tag_number=f'PLAN-{i:03d}',
                name=f'Plan Test {i}',
                breed_status='Foundation',
                date_of_birth='2020-01-01',
                current_status=CowStatus.LACTATING,
                is_active=True,
            )
            db.session.add(cow)
            cows.append(cow)
        db.session.commit()

        for i, cow in enumerate(cows):
            client.post(
                f'/api/v1/animals/{cow.id}/yield-target',
                json={'target_liters': 2.5},
                headers={'Authorization': f'Bearer {auth_token}'},
            )

        response = client.get(
            '/api/v1/herd/feeding-plan/from-targets',
            headers={'Authorization': f'Bearer {auth_token}'},
        )
        assert response.status_code == 200
        data = response.get_json()
        assert data['herd_total_target_liters'] == 5.0
        assert data['active_lactating_count'] == 2
        assert len(data['cow_breakdown']) == 2
        assert 'farmer_reasoning' in data

    def test_get_herd_plan_no_targets(self, client, auth_token):
        """Test that no targets returns 400."""
        response = client.get(
            '/api/v1/herd/feeding-plan/from-targets',
            headers={'Authorization': f'Bearer {auth_token}'},
        )
        assert response.status_code == 400

    def test_post_herd_plan_custom_targets(self, client, auth_token):
        """Test calculating herd plan from custom targets."""
        response = client.post(
            '/api/v1/herd/feeding-plan/custom',
            json={
                'cow_targets': [
                    {'cow_id': 1, 'target_liters': 2.5},
                    {'cow_id': 2, 'target_liters': 2.0},
                ],
                'baseline_herd_meal_kg': 4.0,
            },
            headers={'Authorization': f'Bearer {auth_token}'},
        )
        assert response.status_code == 200
        data = response.get_json()
        assert data['herd_total_target_liters'] == 4.5
        assert data['active_cow_count'] == 2

    def test_post_herd_plan_custom_empty_targets(self, client, auth_token):
        """Test that empty cow_targets returns 400."""
        response = client.post(
            '/api/v1/herd/feeding-plan/custom',
            json={'cow_targets': []},
            headers={'Authorization': f'Bearer {auth_token}'},
        )
        assert response.status_code == 400

    def test_post_herd_plan_custom_with_frequency(self, client, auth_token):
        """Test custom plan with milking frequency override."""
        response = client.post(
            '/api/v1/herd/feeding-plan/custom',
            json={
                'cow_targets': [
                    {'cow_id': 1, 'target_liters': 25.0},  # High load
                ],
                'milking_frequency': 2,  # Override to 2
            },
            headers={'Authorization': f'Bearer {auth_token}'},
        )
        assert response.status_code == 200
        data = response.get_json()
        assert data['used_milking_frequency'] == 2
