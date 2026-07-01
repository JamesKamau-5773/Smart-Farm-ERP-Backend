import json
from datetime import date, datetime

from tests.base import BaseTestCase
from app.models.user import Role
from app.models.livestock import Cow, BreedingLog, SemenInventory, MedicalRecord
from app.models.supply import MilkLog
from app import db

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

    def test_canonical_herd_alias_route(self):
        """Canonical frontend path should work without /api/operations/api duplication."""
        self._login('farmer', 'password')
        with self.client:
            response = self.client.get('/api/herd')
            self.assertEqual(response.status_code, 200)
            payload = json.loads(response.data.decode())
            self.assertIn('items', payload)
            self.assertIn('meta', payload)

    def test_export_animal_passport_pdf(self):
        """Test exporting a cow passport as a PDF."""
        vet = self.create_user(username='vet', password='password', role=Role.VET)

        semen = SemenInventory(
            tenant_id=self.tenant.id,
            bull_name='Jivu Prime',
            straw_code='STRAW-001',
            breed='Friesian',
            provider='Farm Genetics',
            stock_level=3,
        )
        db.session.add(semen)
        db.session.flush()

        db.session.add_all([
            MilkLog(
                tenant_id=self.tenant.id,
                cow_id=self.cow.id,
                amount_liters=18.25,
                session='Morning',
                recorded_by=self.farmer.id,
                timestamp=datetime(2026, 5, 20, 6, 30, 0),
            ),
            MedicalRecord(
                cow_id=self.cow.id,
                vet_id=vet.id,
                visit_date=datetime(2026, 5, 18, 10, 15, 0),
                diagnosis='Mild mastitis',
                medication='Oxytetracycline',
                withdrawal_days_recommended=3,
                remarks='Improving after treatment.',
            ),
            BreedingLog(
                tenant_id=self.tenant.id,
                cow_id=self.cow.id,
                semen_id=semen.id,
                insemination_date=date(2026, 5, 1),
                expected_calving_date=date(2027, 2, 5),
                status='Pregnant',
            ),
        ])
        db.session.commit()

        self._login('farmer', 'password')
        with self.client:
            response = self.client.get(f'/api/v1/export/animal/{self.cow.id}/pdf')

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.mimetype, 'application/pdf')
            self.assertIn('attachment', response.headers.get('Content-Disposition', ''))
            self.assertTrue(response.data.startswith(b'%PDF'))
