import json
from datetime import date, datetime, timezone
from decimal import Decimal

from app import db
from app.models.livestock import Cow, CowStatus
from app.models.supply import MilkDisposition, MilkLog
from app.models.user import Role
from tests.base import BaseTestCase


class MilkDispositionTestCase(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.farmer = self.create_user(username='farmer', password='password', role=Role.FARMER)
        self.producer = Cow(
            tag_number='MILKER-001',
            date_of_birth=date(2022, 1, 1),
            status=CowStatus.LACTATING,
        )
        self.calf = Cow(
            tag_number='CALF-001',
            name='Young One',
            date_of_birth=date.today(),
            status=CowStatus.CALF,
        )
        db.session.add_all([self.producer, self.calf])
        db.session.flush()
        db.session.add(MilkLog(
            tenant_id=self.farmer.tenant_id,
            cow_id=self.producer.id,
            amount_liters=Decimal('10.00'),
            session='Morning',
            timestamp=datetime.now(timezone.utc),
            recorded_by=self.farmer.id,
            is_saleable=True,
            anomaly_flag=False,
        ))
        db.session.commit()
        self.client.post(
            '/api/auth/login',
            data=json.dumps({'username': 'farmer', 'password': 'password'}),
            content_type='application/json',
        )

    def test_record_and_list_calf_feeding(self):
        response = self.client.post(
            '/api/production/milk-dispositions',
            data=json.dumps({
                'type': 'CALF_FEED',
                'calf_id': self.calf.id,
                'liters': 3,
                'date': date.today().isoformat(),
                'notes': 'Morning bottle',
            }),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 201)
        payload = json.loads(response.data.decode())['disposition']
        self.assertEqual(payload['type'], 'CALF_FEED')
        self.assertEqual(payload['liters'], 3.0)
        self.assertEqual(payload['calf']['tag_number'], 'CALF-001')
        self.assertEqual(MilkDisposition.query.count(), 1)

        list_response = self.client.get(
            f'/api/production/milk-dispositions?date={date.today().isoformat()}'
        )
        self.assertEqual(list_response.status_code, 200)
        self.assertEqual(json.loads(list_response.data.decode())['count'], 1)

        dashboard_response = self.client.get('/api/dashboard')
        self.assertEqual(dashboard_response.status_code, 200)
        dashboard = json.loads(dashboard_response.data.decode())
        self.assertEqual(dashboard['calf_fed_liters'], 3.0)
        self.assertEqual(dashboard['remaining_milk_liters'], 7.0)

    def test_calf_feeding_cannot_exceed_available_milk(self):
        response = self.client.post(
            '/api/production/milk-dispositions',
            data=json.dumps({'calf_id': self.calf.id, 'liters': 11}),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 409)
        self.assertIn('Available: 10.00 liters', json.loads(response.data.decode())['error'])
        self.assertEqual(MilkDisposition.query.count(), 0)

    def test_calf_feeding_rejects_non_calf_animal(self):
        response = self.client.post(
            '/api/production/milk-dispositions',
            data=json.dumps({'calf_id': self.producer.id, 'liters': 1}),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(json.loads(response.data.decode())['error'], 'Selected animal must have Calf status.')

    def test_calf_feeding_rejects_unsupported_disposition_type(self):
        response = self.client.post(
            '/api/production/milk-dispositions',
            data=json.dumps({'type': 'SOLD', 'calf_id': self.calf.id, 'liters': 1}),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(json.loads(response.data.decode())['error'], 'type must be CALF_FEED.')
