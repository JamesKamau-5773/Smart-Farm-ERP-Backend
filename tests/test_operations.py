import json
from tests.base import BaseTestCase
from app.models.user import User, Role
from app.models.livestock import Cow
from app import db

class OperationsTestCase(BaseTestCase):

    def setUp(self):
        super().setUp()
        self.farmer = User(username='farmer', password='password', role=Role.FARMER)
        db.session.add(self.farmer)
        db.session.commit()

    def _login(self, username, password):
        return self.client.post(
            '/api/auth/login',
            data=json.dumps(dict(username=username, password=password)),
            content_type='application/json'
        )

    def test_add_cow(self):
        """Test adding a new cow."""
        self._login('farmer', 'password')
        with self.client:
            response = self.client.post(
                '/api/operations/cows',
                data=json.dumps(dict(
                    tag_number='COW002',
                    date_of_birth='2022-01-01',
                    gender='Female',
                    breed='Friesian'
                )),
                content_type='application/json'
            )
            self.assertEqual(response.status_code, 201)
            data = json.loads(response.data.decode())
            self.assertEqual(data['message'], 'Cow COW002 registered successfully.')

    def test_record_milk_production(self):
        """Test recording milk production."""
        cow = Cow(tag_number='COW001', farmer_id=self.farmer.id)
        db.session.add(cow)
        db.session.commit()

        self._login('farmer', 'password')
        with self.client:
            response = self.client.post(
                f'/api/operations/cows/{cow.id}/milk',
                data=json.dumps(dict(
                    amount_liters=20.5
                )),
                content_type='application/json'
            )
            self.assertEqual(response.status_code, 201)
            data = json.loads(response.data.decode())
            self.assertEqual(data['message'], 'Milk log created successfully.')
