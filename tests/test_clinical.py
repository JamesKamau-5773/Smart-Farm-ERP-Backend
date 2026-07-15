import json
from tests.base import BaseTestCase
from app.models.user import Role
from app.models.livestock import Cow
from app import db
from datetime import date

class ClinicalTestCase(BaseTestCase):

    def setUp(self):
        super().setUp()
        # Create users with different roles
        self.farmer = self.create_user(username='farmer', password='password', role=Role.FARMER)
        self.vet = self.create_user(username='vet', password='password', role=Role.VET)

        # Create a cow
        self.cow = Cow(tag_number='COW001', date_of_birth=date(2022, 1, 1))
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
            self.assertIn('Clinical record', data['message'])

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

    def test_vet_visit_workflow_accepts_frontend_alias_payload(self):
        self._login('farmer', 'password')
        with self.client:
            response = self.client.post(
                '/api/clinical/vet-visits',
                data=json.dumps({
                    'date': '2026-07-03',
                    'cow': 'c-oo1',
                    'reason': 'cow limping',
                    'diagnosis': 'infected hoof',
                    'meds': 'antibiotic',
                    'recommendations': 'apply for 1 week',
                    'followUp': '2026-07-24',
                }),
                content_type='application/json',
            )
            self.assertEqual(response.status_code, 201)
            payload = json.loads(response.data.decode())
            self.assertIn('visit', payload)
            self.assertEqual(payload['visit']['cow_id'], self.cow.id)
            self.assertEqual(payload['visit']['reason_for_visit'], 'cow limping')
            self.assertEqual(payload['visit']['follow_up_date'], '2026-07-24')

    def test_vet_visit_workflow_accepts_cow_name_in_alias_payload(self):
        self.cow.name = 'Mwadie'
        db.session.commit()

        self._login('farmer', 'password')
        with self.client:
            response = self.client.post(
                '/api/clinical/vet-visits',
                data=json.dumps({
                    'date': '2026-07-12',
                    'cow': 'mwadie',
                    'reason': 'poor feeding',
                    'diagnosis': 'milk fever',
                    'meds': ['calcium'],
                }),
                content_type='application/json',
            )
            self.assertEqual(response.status_code, 201)
            payload = json.loads(response.data.decode())
            self.assertEqual(payload['visit']['cow_id'], self.cow.id)
            self.assertEqual(payload['visit']['reason_for_visit'], 'poor feeding')
