import json
from tests.base import BaseTestCase
from app.models.user import User, Role
from app.models.livestock import Cow
from app import db

class ClinicalTestCase(BaseTestCase):

    def setUp(self):
        super().setUp()
        # Create users with different roles
        self.farmer = User(username='farmer', password='password', role=Role.FARMER)
        self.vet = User(username='vet', password='password', role=Role.VET)
        db.session.add_all([self.farmer, self.vet])
        db.session.commit()

        # Create a cow
        self.cow = Cow(tag_number='COW001', farmer_id=self.farmer.id)
        db.session.add(self.cow)
        db.session.commit()

    def _login(self, username, password):
        return self.client.post(
            '/api/auth/login',
            data=json.dumps(dict(username=username, password=password)),
            content_type='application/json'
        )

    def test_log_vet_visit(self):
        """Test logging a vet visit."""
        self._login('vet', 'password')
        with self.client:
            response = self.client.post(
                f'/api/clinical/cows/{self.cow.id}/medical',
                data=json.dumps(dict(
                    diagnosis='Mastitis',
                    medication='Penicillin',
                    withdrawal_days=7
                )),
                content_type='application/json'
            )
            self.assertEqual(response.status_code, 201)
            data = json.loads(response.data.decode())
            self.assertIn('Medical record created for cow', data['message'])

    def test_toggle_farmer_hardlock(self):
        """Test toggling the hardlock by a farmer."""
        self._login('farmer', 'password')
        with self.client:
            response = self.client.put(
                f'/api/clinical/cows/{self.cow.id}/hardlock',
                data=json.dumps(dict(is_locked=True)),
                content_type='application/json'
            )
            self.assertEqual(response.status_code, 200)
            data = json.loads(response.data.decode())
            self.assertIn('is now LOCKED', data['message'])
