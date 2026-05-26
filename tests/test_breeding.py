import json
from datetime import date

from app import db
from app.models.livestock import Cow
from app.models.supply import MilkLog, MilkSession
from app.models.user import Role
from tests.base import BaseTestCase


class BreedingTestCase(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.farmer = self.create_user(username='farmer', password='password', role=Role.FARMER)
        self.cow = Cow(tag_number='COWBR001', date_of_birth=date(2022, 1, 1))
        db.session.add(self.cow)
        db.session.commit()

    def _login(self):
        return self.client.post(
            '/api/auth/login',
            data=json.dumps(dict(username='farmer', password='password')),
            content_type='application/json'
        )

    def test_create_inventory_and_log_insemination(self):
        self._login()

        with self.client:
            inv_response = self.client.post(
                '/api/operations/semen-inventory',
                data=json.dumps(
                    dict(
                        bull_name='BULL-A',
                        straw_code='AI-STR-001',
                        breed='Friesian',
                        stock_level=3,
                        traits_to_improve=['Volume'],
                    )
                ),
                content_type='application/json'
            )
            self.assertEqual(inv_response.status_code, 201)
            inv_data = json.loads(inv_response.data.decode())
            semen_id = inv_data['id']

            log_response = self.client.post(
                '/api/operations/breeding-logs',
                data=json.dumps(
                    dict(
                        cow_id=self.cow.id,
                        semen_id=semen_id,
                        insemination_date='2026-05-20',
                    )
                ),
                content_type='application/json'
            )
            self.assertEqual(log_response.status_code, 201)
            log_data = json.loads(log_response.data.decode())
            self.assertIn('expected_calving_date', log_data)

    def test_update_breeding_status(self):
        self._login()

        with self.client:
            inv_response = self.client.post(
                '/api/operations/semen-inventory',
                data=json.dumps(dict(bull_name='BULL-B', straw_code='AI-STR-002', breed='Ayrshire', stock_level=2)),
                content_type='application/json'
            )
            semen_id = json.loads(inv_response.data.decode())['id']

            log_response = self.client.post(
                '/api/operations/breeding-logs',
                data=json.dumps(dict(cow_id=self.cow.id, semen_id=semen_id, insemination_date='2026-05-21')),
                content_type='application/json'
            )
            log_id = json.loads(log_response.data.decode())['breeding_log_id']

            update_response = self.client.put(
                f'/api/operations/breeding-logs/{log_id}/status',
                data=json.dumps(dict(status='Pregnant')),
                content_type='application/json'
            )
            self.assertEqual(update_response.status_code, 200)
            update_data = json.loads(update_response.data.decode())
            self.assertEqual(update_data['status'], 'Pregnant')

    def test_exact_patch_outcome_route_updates_livestock_status(self):
        self._login()

        with self.client:
            inv_response = self.client.post(
                '/api/operations/semen-inventory',
                data=json.dumps(dict(bull_name='BULL-C', straw_code='AI-STR-004', breed='Holstein', stock_level=1)),
                content_type='application/json'
            )
            semen_id = json.loads(inv_response.data.decode())['id']

            log_response = self.client.post(
                '/api/operations/breeding-logs',
                data=json.dumps(dict(cow_id=self.cow.id, semen_id=semen_id, insemination_date='2026-05-23')),
                content_type='application/json'
            )
            log_id = json.loads(log_response.data.decode())['breeding_log_id']

            outcome_response = self.client.patch(
                f'/api/v1/breeding/insemination/{log_id}/outcome',
                data=json.dumps(dict(status='Pregnant')),
                content_type='application/json'
            )
            self.assertEqual(outcome_response.status_code, 200)
            outcome_data = json.loads(outcome_response.data.decode())
            self.assertEqual(outcome_data['message'], 'Insemination marked as Pregnant')

            refreshed_cow = db.session.get(Cow, self.cow.id)
            self.assertEqual(refreshed_cow.current_status, 'Pregnant')

    def test_bull_performance_includes_butterfat(self):
        self._login()

        with self.client:
            inv_response = self.client.post(
                '/api/operations/semen-inventory',
                data=json.dumps(dict(bull_name='BULL-FAT', straw_code='AI-STR-003', breed='Jersey', stock_level=2)),
                content_type='application/json'
            )
            semen_id = json.loads(inv_response.data.decode())['id']

            log_response = self.client.post(
                '/api/operations/breeding-logs',
                data=json.dumps(dict(cow_id=self.cow.id, semen_id=semen_id, insemination_date='2026-05-22')),
                content_type='application/json'
            )
            log_id = json.loads(log_response.data.decode())['breeding_log_id']

            update_response = self.client.put(
                f'/api/operations/breeding-logs/{log_id}/status',
                data=json.dumps(dict(status='Pregnant')),
                content_type='application/json'
            )
            self.assertEqual(update_response.status_code, 200)

            milk_log = MilkLog(
                cow_id=self.cow.id,
                amount_liters=18.0,
                session=MilkSession.MORNING,
                recorded_by=self.farmer.id,
                butterfat_pct=4.8,
                is_saleable=True,
                anomaly_flag=False,
            )
            db.session.add(milk_log)
            db.session.commit()

            perf_response = self.client.get('/api/operations/breeding/performance')
            self.assertEqual(perf_response.status_code, 200)
            perf_data = json.loads(perf_response.data.decode())
            summary = perf_data['summary']
            self.assertTrue(any(item['avg_butterfat_pct_for_pregnant_progeny'] is not None for item in summary))
