import json
from tests.base import BaseTestCase
from app.models.user import Role
from app.models.livestock import Cow
from app import db
from datetime import date

class OperationsTestCase(BaseTestCase):

    def setUp(self):
        super().setUp()
        self.farmer = self.create_user(username='farmer', password='password', role=Role.FARMER)
        self.cow = Cow(tag_number='COW001', date_of_birth=date(2022, 1, 1))
        db.session.add(self.cow)
        db.session.commit()

    def _login(self, username, password):
        return self.client.post(
            '/api/auth/login',
            data=json.dumps(dict(username=username, password=password)),
            content_type='application/json'
        )

    def test_record_milk_production(self):
        """Test recording milk production."""
        self._login('farmer', 'password')
        with self.client:
            response = self.client.post(
                f'/api/operations/cows/{self.cow.id}/milk',
                data=json.dumps(dict(
                    amount=20.5,
                    session='Morning'
                )),
                content_type='application/json'
            )
            self.assertEqual(response.status_code, 201)
            data = json.loads(response.data.decode())
            self.assertEqual(data['message'], 'Milk logged successfully.')
