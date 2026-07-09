import json
from datetime import date, datetime, timezone

from tests.base import BaseTestCase
from app.models.user import Role
from app.models.livestock import Cow, BreedingLog, SemenInventory, MedicalRecord
from app.models.supply import MilkLog
from app import db
from flask_jwt_extended import create_access_token

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

    def test_animal_timeline_events_can_be_saved_and_listed(self):
        self._login('farmer', 'password')

        with self.client:
            create_resp = self.client.post(
                f'/api/operations/api/animals/{self.cow.id}/events',
                data=json.dumps({
                    'event_type': 'vaccination',
                    'title': 'Vaccination administered',
                    'description': 'Annual FMD vaccine given.',
                    'event_date': '2026-07-02T08:30:00+00:00',
                    'event_data': {'product': 'FMD', 'batch': 'B-100'},
                }),
                content_type='application/json',
            )
            self.assertEqual(create_resp.status_code, 201)
            created = json.loads(create_resp.data.decode())
            self.assertEqual(created['cow_id'], self.cow.id)
            self.assertEqual(created['event_type'], 'vaccination')
            self.assertEqual(created['title'], 'Vaccination administered')

            list_resp = self.client.get(f'/api/operations/api/animals/{self.cow.id}/events')
            self.assertEqual(list_resp.status_code, 200)
            payload = json.loads(list_resp.data.decode())
            self.assertIn('items', payload)
            self.assertEqual(len(payload['items']), 1)
            self.assertEqual(payload['items'][0]['title'], 'Vaccination administered')

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

    def test_admin_can_verify_production_yield(self):
        admin = self.create_user(username='admin', password='password', role=Role.ADMIN)
        log = MilkLog(
            tenant_id=self.tenant.id,
            cow_id=self.cow.id,
            amount_liters=11.0,
            session='Morning',
            recorded_by=self.farmer.id,
            is_saleable=True,
            anomaly_flag=False,
        )
        db.session.add(log)
        db.session.commit()

        token = create_access_token(
            identity=str(admin.id),
            additional_claims={'role': Role.ADMIN, 'tenant_id': self.tenant.id, 'farm_id': self.farm.id},
        )

        response = self.client.patch(
            f'/api/production/yield/{log.id}/verify',
            headers={'Authorization': f'Bearer {token}'},
        )
        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.data.decode())
        self.assertEqual(payload['id'], log.id)
        self.assertEqual(payload['log_id'], log.id)
        self.assertEqual(payload['status'], 'VERIFIED')
        self.assertEqual(payload['verified_by'], admin.id)
        self.assertIsNotNone(payload['verified_at'])

        db.session.refresh(log)
        self.assertEqual(log.verified_by, admin.id)
        self.assertIsNotNone(log.verified_at)

    def test_verify_production_yield_is_idempotent(self):
        admin = self.create_user(username='admin2', password='password', role=Role.ADMIN)
        verified_at = datetime(2026, 7, 9, 8, 30, tzinfo=timezone.utc)
        log = MilkLog(
            tenant_id=self.tenant.id,
            cow_id=self.cow.id,
            amount_liters=9.5,
            session='Evening',
            recorded_by=self.farmer.id,
            is_saleable=True,
            anomaly_flag=False,
            verified_by=admin.id,
            verified_at=verified_at,
        )
        db.session.add(log)
        db.session.commit()

        token = create_access_token(
            identity=str(admin.id),
            additional_claims={'role': Role.ADMIN, 'tenant_id': self.tenant.id, 'farm_id': self.farm.id},
        )

        response = self.client.patch(
            f'/api/production/yield/{log.id}/verify',
            headers={'Authorization': f'Bearer {token}'},
        )
        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.data.decode())
        self.assertEqual(payload['status'], 'VERIFIED')
        self.assertEqual(payload['verified_by'], admin.id)
        self.assertEqual(
            datetime.fromisoformat(payload['verified_at']).astimezone(timezone.utc),
            verified_at,
        )

    def test_farmer_cannot_verify_production_yield(self):
        self._login('farmer', 'password')
        log = MilkLog(
            tenant_id=self.tenant.id,
            cow_id=self.cow.id,
            amount_liters=13.0,
            session='Morning',
            recorded_by=self.farmer.id,
            is_saleable=True,
            anomaly_flag=False,
        )
        db.session.add(log)
        db.session.commit()

        with self.client:
            response = self.client.patch(f'/api/production/yield/{log.id}/verify')
            self.assertEqual(response.status_code, 403)

    def test_verify_production_yield_respects_tenant_scope(self):
        other_tenant = self.create_tenant(name='Other Tenant')
        other_farm = self.create_farm(tenant=other_tenant, name='Other Farm')
        other_admin = self.create_user(username='otheradmin', password='password', role=Role.ADMIN, tenant=other_tenant)

        log = MilkLog(
            tenant_id=self.tenant.id,
            cow_id=self.cow.id,
            amount_liters=7.0,
            session='Morning',
            recorded_by=self.farmer.id,
            is_saleable=True,
            anomaly_flag=False,
        )
        db.session.add(log)
        db.session.commit()

        token = create_access_token(
            identity=str(other_admin.id),
            additional_claims={'role': Role.ADMIN, 'tenant_id': other_tenant.id, 'farm_id': other_farm.id},
        )

        response = self.client.patch(
            f'/api/production/yield/{log.id}/verify',
            headers={'Authorization': f'Bearer {token}'},
        )
        self.assertEqual(response.status_code, 404)
