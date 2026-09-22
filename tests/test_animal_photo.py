from __future__ import annotations

import io
from datetime import date

from app import db
from app.models.livestock import Cow
from app.models.user import Role
from tests.base import BaseTestCase


class AnimalPhotoTestCase(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.farmer = self.create_user(username='photo_farmer', password='password', role=Role.FARMER)
        self.cow = Cow(tenant_id=self.tenant.id, tag_number='PHOTO001', date_of_birth=date(2022, 1, 1))
        db.session.add(self.cow)
        db.session.commit()

    def _login(self):
        return self.client.post(
            '/api/auth/login',
            json={'username': 'photo_farmer', 'password': 'password'},
        )

    def test_upload_photo_persists_url_and_returns_canonical_dto(self):
        self._login()

        with self.client:
            response = self.client.post(
                f'/api/animals/{self.cow.id}/photo',
                data={'file': (io.BytesIO(b'\xff\xd8\xff\xe0\x00\x10JFIF\x00fake-image-bytes'), 'cow.jpg')},
                content_type='multipart/form-data',
            )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertIsNotNone(payload['photo_url'])
        self.assertTrue(payload['photo_url'].startswith('/uploads/animal_photos/'))

        db.session.refresh(self.cow)
        self.assertEqual(self.cow.photo_url, payload['photo_url'])

        # Photo URL is present on the canonical GET/PATCH DTOs too.
        with self.client:
            get_response = self.client.get(f'/api/animals/{self.cow.id}')
        self.assertEqual(get_response.get_json()['photo_url'], payload['photo_url'])

    def test_upload_photo_rejects_mismatched_content(self):
        self._login()

        with self.client:
            response = self.client.post(
                f'/api/animals/{self.cow.id}/photo',
                data={'file': (io.BytesIO(b'not-an-image'), 'cow.jpg')},
                content_type='multipart/form-data',
            )

        self.assertEqual(response.status_code, 400)

    def test_upload_photo_rejects_disallowed_extension(self):
        self._login()

        with self.client:
            response = self.client.post(
                f'/api/animals/{self.cow.id}/photo',
                data={'file': (io.BytesIO(b'%PDF-1.4 fake pdf'), 'cow.pdf')},
                content_type='multipart/form-data',
            )

        self.assertEqual(response.status_code, 400)

    def test_replace_photo_removes_previous_file(self):
        self._login()

        with self.client:
            first_response = self.client.post(
                f'/api/animals/{self.cow.id}/photo',
                data={'file': (io.BytesIO(b'\x89PNG\r\n\x1a\nfake-png-bytes'), 'first.png')},
                content_type='multipart/form-data',
            )
        first_url = first_response.get_json()['photo_url']

        with self.client:
            second_response = self.client.post(
                f'/api/animals/{self.cow.id}/photo',
                data={'file': (io.BytesIO(b'\xff\xd8\xff\xe0\x00\x10JFIF\x00second'), 'second.jpg')},
                content_type='multipart/form-data',
            )
        second_url = second_response.get_json()['photo_url']

        self.assertNotEqual(first_url, second_url)

        with self.client:
            first_fetch = self.client.get(first_url)
        self.assertEqual(first_fetch.status_code, 404)

        with self.client:
            second_fetch = self.client.get(second_url)
        self.assertEqual(second_fetch.status_code, 200)

    def test_remove_photo_clears_url_and_deletes_file(self):
        self._login()

        with self.client:
            upload_response = self.client.post(
                f'/api/animals/{self.cow.id}/photo',
                data={'file': (io.BytesIO(b'\xff\xd8\xff\xe0\x00\x10JFIF\x00fake'), 'cow.jpg')},
                content_type='multipart/form-data',
            )
        photo_url = upload_response.get_json()['photo_url']

        with self.client:
            delete_response = self.client.delete(f'/api/animals/{self.cow.id}/photo')

        self.assertEqual(delete_response.status_code, 200)
        self.assertIsNone(delete_response.get_json()['photo_url'])

        db.session.refresh(self.cow)
        self.assertIsNone(self.cow.photo_url)

        with self.client:
            fetch_response = self.client.get(photo_url)
        self.assertEqual(fetch_response.status_code, 404)

    def test_upload_photo_requires_file(self):
        self._login()

        with self.client:
            response = self.client.post(
                f'/api/animals/{self.cow.id}/photo',
                data={},
                content_type='multipart/form-data',
            )

        self.assertEqual(response.status_code, 400)
