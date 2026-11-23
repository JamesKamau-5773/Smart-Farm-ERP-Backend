"""GET /uploads/<path>: signed-in users of the owning tenant only."""
import os

from app import db
from app.models.tenant import Tenant
from app.models.user import Role
from app.services.upload_access_service import UploadAccessService
from tests.base import BaseTestCase

PNG = b'\x89PNG\r\n\x1a\n' + b'\x00' * 16


class UploadsAccessTestCase(BaseTestCase):

    def _store(self, relative):
        path = os.path.join(self.app.config['UPLOAD_ROOT'], relative)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'wb') as handle:
            handle.write(PNG)
        return f'/uploads/{relative}'

    def test_anonymous_request_is_refused(self):
        url = self._store(f'animal_photos/tenant_{self.tenant.id}/cow.png')
        self.assertEqual(self.client.get(url).status_code, 401)

    def test_own_tenant_file_is_served_by_cookie_session(self):
        url = self._store(f'animal_photos/tenant_{self.tenant.id}/cow.png')
        self.create_user(username='owner', password='password', role=Role.FARMER)
        # Login sets the session cookie, which is what an <img> request carries.
        self.client.post('/api/auth/login', json={'username': 'owner', 'password': 'password'})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, PNG)
        self.assertIn('private', response.headers['Cache-Control'])

    def test_other_tenant_file_is_not_found(self):
        other = Tenant(name='Other', tenant_type='single')
        db.session.add(other)
        db.session.commit()
        url = self._store(f'ai_certificates/tenant_{other.id}/cert.png')
        headers = self.get_auth_headers(Role.FARMER)
        self.assertEqual(self.client.get(url, headers=headers).status_code, 404)

    def test_paths_outside_the_tenant_folders_are_refused(self):
        user = self.create_user(username='hand', password='password', role=Role.FARM_HAND)
        tid = self.tenant.id
        for path in (
            f'animal_photos/tenant_{tid}/../../secret.png',
            f'animal_photos/tenant_{tid}',
            f'other_folder/tenant_{tid}/x.png',
            f'/animal_photos/tenant_{tid}/x.png',
            f'animal_photos/tenant_{tid}//x.png',
            'animal_photos\\tenant_1\\x.png',
        ):
            self.assertIsNone(UploadAccessService.allowed_path(user, path), path)
        self.assertEqual(
            UploadAccessService.allowed_path(user, f'animal_photos/tenant_{tid}/x.png'),
            f'animal_photos/tenant_{tid}/x.png',
        )

    def test_traversal_over_http_is_not_served(self):
        self._store(f'animal_photos/tenant_{self.tenant.id}/cow.png')
        headers = self.get_auth_headers(Role.FARMER)
        response = self.client.get(f'/uploads/animal_photos/tenant_{self.tenant.id}/%2e%2e/%2e%2e/../config.py', headers=headers)
        self.assertEqual(response.status_code, 404)
