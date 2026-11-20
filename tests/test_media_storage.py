"""Uploads on Cloudinary (production) with the SDK mocked; local disk stays the default."""
from __future__ import annotations

import io
from datetime import date
from unittest.mock import MagicMock, patch

from werkzeug.datastructures import FileStorage

from app import db
from app.models.finance import TransactionAttachment
from app.models.livestock import Cow
from app.models.user import Role
from app.services.media_storage import MediaStorage, MediaStorageError, cloudinary_public_id_from_url
from tests.base import BaseTestCase

PNG = b'\x89PNG\r\n\x1a\n' + b'\x00' * 64
JPG = b'\xff\xd8\xff\xe0\x00\x10JFIF\x00photo-bytes'
CLOUD = 'maziwa-test'


def _uploaded(public_id, resource_type='image', file_format='jpg', delivery='upload', version=1732100000):
    return {
        'public_id': public_id,
        'resource_type': resource_type,
        'format': file_format,
        'type': delivery,
        'secure_url': f'https://res.cloudinary.com/{CLOUD}/{resource_type}/{delivery}/v{version}/{public_id}.{file_format}',
    }


class CloudinaryCase(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.app.config.update(MEDIA_STORAGE='cloudinary', CLOUDINARY_URL=f'cloudinary://key123:secret456@{CLOUD}',
                               CLOUDINARY_FOLDER='maziwa')
        self.upload = patch('cloudinary.uploader.upload').start()
        self.destroy = patch('cloudinary.uploader.destroy').start()
        self.addCleanup(patch.stopall)

    def tearDown(self):
        self.app.config.update(MEDIA_STORAGE='local', CLOUDINARY_URL=None)
        super().tearDown()


class CloudinaryUrlTests(CloudinaryCase):
    def test_reads_the_public_id_from_this_accounts_links_only(self):
        base = f'https://res.cloudinary.com/{CLOUD}'
        self.assertEqual(cloudinary_public_id_from_url(f'{base}/image/upload/v17/maziwa/animal_photos/tenant_1/5_ab.jpg'),
                         ('maziwa/animal_photos/tenant_1/5_ab', 'image', 'upload'))
        # With transformations before the version.
        self.assertEqual(cloudinary_public_id_from_url(f'{base}/image/upload/w_400,q_auto/v17/maziwa/x.png'),
                         ('maziwa/x', 'image', 'upload'))
        # Raw files keep their extension in the public id.
        self.assertEqual(cloudinary_public_id_from_url(f'{base}/raw/upload/v1/maziwa/doc.pdf'), ('maziwa/doc.pdf', 'raw', 'upload'))
        self.assertIsNone(cloudinary_public_id_from_url('https://res.cloudinary.com/someone-else/image/upload/v1/x.jpg'))
        self.assertIsNone(cloudinary_public_id_from_url('https://example.com/image/upload/v1/x.jpg'))
        self.assertIsNone(cloudinary_public_id_from_url('/uploads/animal_photos/tenant_1/x.jpg'))

    def test_a_malformed_cloudinary_url_is_refused_before_anything_is_sent(self):
        self.app.config['CLOUDINARY_URL'] = 'https://not-a-cloudinary-url'
        with self.assertRaises(MediaStorageError):
            MediaStorage.save_public(FileStorage(io.BytesIO(PNG), filename='x.png'), folder='animal_photos/tenant_1', name='x', extension='.png')
        self.upload.assert_not_called()


class CowPhotoOnCloudinaryTests(CloudinaryCase):
    def setUp(self):
        super().setUp()
        self.create_user(username='photo_farmer', password='password', role=Role.FARMER)
        self.cow = Cow(tenant_id=self.tenant.id, tag_number='CLD001', date_of_birth=date(2022, 1, 1))
        db.session.add(self.cow)
        db.session.commit()
        self.client.post('/api/auth/login', json={'username': 'photo_farmer', 'password': 'password'})

    def _post_photo(self):
        return self.client.post(f'/api/animals/{self.cow.id}/photo',
                                data={'file': (io.BytesIO(JPG), 'cow.jpg')}, content_type='multipart/form-data')

    def test_photo_is_stored_on_cloudinary_and_the_replaced_one_removed(self):
        self.upload.side_effect = lambda source, **options: _uploaded(f"{options['folder']}/{options['public_id']}")

        first = self._post_photo()
        self.assertEqual(first.status_code, 200, first.get_json())
        first_url = first.get_json()['photo_url']
        self.assertTrue(first_url.startswith(f'https://res.cloudinary.com/{CLOUD}/image/upload/'))
        options = self.upload.call_args.kwargs
        self.assertEqual((options['folder'], options['type'], options['resource_type']),
                         (f'maziwa/animal_photos/tenant_{self.tenant.id}', 'upload', 'auto'))

        second_url = self._post_photo().get_json()['photo_url']
        self.assertNotEqual(first_url, second_url)
        public_id, _resource, _type = cloudinary_public_id_from_url(first_url)
        self.destroy.assert_called_once_with(public_id, resource_type='image', type='upload', invalidate=True)

        db.session.refresh(self.cow)
        self.assertEqual(self.cow.photo_url, second_url)

    def test_removing_the_photo_deletes_it_on_cloudinary(self):
        self.upload.side_effect = lambda source, **options: _uploaded(f"{options['folder']}/{options['public_id']}")
        url = self._post_photo().get_json()['photo_url']
        response = self.client.delete(f'/api/animals/{self.cow.id}/photo')
        self.assertIn(response.status_code, (200, 204), response.get_data(as_text=True))
        self.destroy.assert_called_once()
        db.session.refresh(self.cow)
        self.assertIsNone(self.cow.photo_url)
        self.assertTrue(url)


class ReceiptPhotoOnCloudinaryTests(CloudinaryCase):
    def setUp(self):
        super().setUp()
        self.headers = self.get_auth_headers()

    def _expense(self):
        response = self.client.post('/api/finance/ledger', headers=self.headers,
                                    json={'transaction_type': 'Expense', 'category': 'Transport', 'amount': 1200, 'paid_to': 'Matatu'})
        self.assertEqual(response.status_code, 201, response.get_json())
        return response.get_json()

    def test_receipt_photos_are_authenticated_files_served_only_through_the_api(self):
        self.upload.side_effect = lambda source, **options: _uploaded(
            f"{options['folder']}/{options['public_id']}", file_format='png', delivery=options['type'])
        entry = self._expense()

        upload = self.client.post(f'/api/finance/transactions/{entry["id"]}/attachments',
                                  data={'file': (io.BytesIO(PNG), 'receipt.png')}, headers=self.headers,
                                  content_type='multipart/form-data')
        self.assertEqual(upload.status_code, 201, upload.get_json())
        options = self.upload.call_args.kwargs
        self.assertEqual((options['type'], options['folder']), ('authenticated', f'maziwa/private/tenant_{self.tenant_id}'))
        stored = TransactionAttachment.query.one().stored_path
        self.assertTrue(stored.startswith(f'cloudinary:image/png/maziwa/private/tenant_{self.tenant_id}/'), stored)

        fetched = MagicMock(status_code=200, content=PNG)
        with patch('app.services.media_storage.requests.get', return_value=fetched) as get:
            download = self.client.get(upload.get_json()['url'], headers=self.headers)
        self.assertEqual((download.status_code, download.data), (200, PNG))
        signed_url = get.call_args.args[0]
        self.assertIn('/image/authenticated/s--', signed_url)
        # Without signing in there is still no way in.
        self.assertEqual(self.app.test_client().get(upload.get_json()['url']).status_code, 401)

    def test_a_file_cloudinary_no_longer_has_reads_as_missing(self):
        self.upload.side_effect = lambda source, **options: _uploaded(
            f"{options['folder']}/{options['public_id']}", file_format='png', delivery=options['type'])
        entry = self._expense()
        url = self.client.post(f'/api/finance/transactions/{entry["id"]}/attachments',
                               data={'file': (io.BytesIO(PNG), 'receipt.png')}, headers=self.headers,
                               content_type='multipart/form-data').get_json()['url']
        with patch('app.services.media_storage.requests.get', return_value=MagicMock(status_code=404, content=b'')):
            self.assertEqual(self.client.get(url, headers=self.headers).status_code, 404)

    def test_a_storage_failure_is_reported_and_nothing_is_saved(self):
        self.upload.side_effect = RuntimeError('Cloudinary is down')
        entry = self._expense()
        response = self.client.post(f'/api/finance/transactions/{entry["id"]}/attachments',
                                    data={'file': (io.BytesIO(PNG), 'receipt.png')}, headers=self.headers,
                                    content_type='multipart/form-data')
        self.assertEqual((response.status_code, response.get_json()['code']), (502, 'STORAGE_UNAVAILABLE'))
        self.assertEqual(TransactionAttachment.query.count(), 0)


class LocalStorageStaysTheDefaultTests(BaseTestCase):
    def test_without_cloudinary_files_go_to_disk(self):
        self.assertEqual(self.app.config['MEDIA_STORAGE'], 'local')
        url = MediaStorage.save_public(FileStorage(io.BytesIO(PNG), filename='x.png'), folder='animal_photos/tenant_1', name='local_check', extension='.png')
        self.assertEqual(url, '/uploads/animal_photos/tenant_1/local_check.png')
        MediaStorage.delete_public(url)
