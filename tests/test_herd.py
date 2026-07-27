import json
from datetime import date

from app import db
from app.models.livestock import Cow
from app.models.supply import MilkLog, MilkSession, AnimalYieldTarget
from tests.base import BaseTestCase


class HerdAPITestCase(BaseTestCase):

    def setUp(self):
        super().setUp()
        self.auth_headers = self.get_auth_headers()
        self.farmer_id = self.farmer.id

    def test_soft_delete_cow_archives_record(self):
        """Test that 'deleting' a cow sets its is_active flag to False (soft delete)."""
        original_tag = 'COW-DEL-01'
        cow_to_archive = Cow(
            tenant_id=self.tenant.id,
            tag_number=original_tag,
            date_of_birth=date(2020, 1, 1),
            is_active=True
        )
        db.session.add(cow_to_archive)
        db.session.commit()
        cow_id = cow_to_archive.id

        with self.client:
            response = self.client.delete(
                f'/api/herd/{cow_id}',
                headers=self.auth_headers
            )

        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data.decode())
        self.assertIn('successfully archived and tag number freed', data['message'])

        # Verify the cow is now inactive in the database
        archived_cow = Cow.query.get(cow_id)
        self.assertIsNotNone(archived_cow)
        self.assertFalse(archived_cow.is_active)
        self.assertNotEqual(archived_cow.tag_number, original_tag)
        self.assertTrue(archived_cow.tag_number.startswith(f"{original_tag}_archived_"))

    def test_list_herd_excludes_inactive_cows_by_default(self):
        """Test that GET /api/herd only returns active cows by default."""
        active_cow = Cow(
            tenant_id=self.tenant.id,
            tag_number='ACTIVE-COW',
            date_of_birth=date(2021, 1, 1),
            is_active=True
        )
        inactive_cow = Cow(
            tenant_id=self.tenant.id,
            tag_number='INACTIVE-COW',
            date_of_birth=date(2020, 1, 1),
            is_active=False
        )
        db.session.add_all([active_cow, inactive_cow])
        db.session.commit()

        with self.client:
            # Default request should only return the active cow
            response = self.client.get('/api/herd', headers=self.auth_headers)
            self.assertEqual(response.status_code, 200)
            data = json.loads(response.data.decode())
            self.assertEqual(len(data['items']), 1)
            self.assertEqual(data['items'][0]['tag_number'], 'ACTIVE-COW')

            # Request with include_inactive=true should return both
            response_all = self.client.get('/api/herd?include_inactive=true', headers=self.auth_headers)
            self.assertEqual(response_all.status_code, 200)
            data_all = json.loads(response_all.data.decode())
            self.assertEqual(len(data_all['items']), 2)