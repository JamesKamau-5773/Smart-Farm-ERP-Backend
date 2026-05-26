import json
from datetime import date

from app import db
from app.models.livestock import Cow
from app.models.user import Role
from tests.base import BaseTestCase


class LivestockCompatibilityTestCase(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.farmer = self.create_user(username='farmer', password='password', role=Role.FARMER)
        self.vet = self.create_user(username='vet', password='password', role=Role.VET)
        self.cow = Cow(tag_number='COW-COMPAT-001', date_of_birth=date(2022, 1, 1))
        db.session.add(self.cow)
        db.session.commit()

    def _login(self, username):
        return self.client.post(
            '/api/auth/login',
            data=json.dumps(dict(username=username, password='password')),
            content_type='application/json'
        )

    def test_livestock_milk_route_works(self):
        self._login('farmer')
        with self.client:
            response = self.client.post(
                f'/api/operations/livestock/{self.cow.id}/milk',
                data=json.dumps(dict(amount=12.5, session='Morning')),
                content_type='application/json'
            )
            self.assertEqual(response.status_code, 201)
            data = json.loads(response.data.decode())
            self.assertEqual(data['message'], 'Milk logged successfully.')

    def test_livestock_clinical_routes_work(self):
        self._login('vet')
        with self.client:
            response = self.client.post(
                f'/api/clinical/livestock/{self.cow.id}/medical',
                data=json.dumps(dict(diagnosis='Routine check', medication='None', withdrawal_days=0)),
                content_type='application/json'
            )
            self.assertEqual(response.status_code, 201)
            data = json.loads(response.data.decode())
            self.assertIn('Clinical record', data['message'])
