"""BR-019: milk list status filter, status counts, complete rows and session values.
BR-016: the phone-number statement route is disabled."""
import json
from datetime import date, datetime, timezone

from app import db
from app.models.livestock import Cow
from app.models.supply import MilkLog
from app.models.user import Role
from tests.base import BaseTestCase


class MilkListStatusTestCase(BaseTestCase):

    def setUp(self):
        super().setUp()
        self.farmer = self.create_user(username='farmer', password='password', role=Role.FARMER)
        self.cow = Cow(tag_number='COW001', date_of_birth=date(2022, 1, 1))
        db.session.add(self.cow)
        db.session.commit()

        def log(amount, session, **flags):
            return MilkLog(tenant_id=self.tenant.id, cow_id=self.cow.id, amount_liters=amount,
                           session=session, recorded_by=self.farmer.id, **flags)

        now = datetime.now(timezone.utc)
        db.session.add_all([
            log(10, 'Morning', is_saleable=True, anomaly_flag=False),                       # RECORDED
            log(11, 'Evening', is_saleable=True, anomaly_flag=False,
                status=MilkLog.STATUS_VERIFIED, verified_at=now),                            # VERIFIED
            log(4, 'Midday', is_saleable=True, anomaly_flag=True),                           # FLAGGED
            log(3, 'Morning', is_saleable=False, anomaly_flag=False, source='whatsapp'),     # ISOLATED
            # Verified wins over the anomaly flag, as in the row's own status.
            log(5, 'Evening', is_saleable=True, anomaly_flag=True, verified_at=now),         # VERIFIED
        ])
        db.session.commit()
        self.client.post('/api/auth/login', data=json.dumps({'username': 'farmer', 'password': 'password'}),
                         content_type='application/json')

    def _list(self, query=''):
        response = self.client.get(f'/api/production/yield{query}')
        return response.status_code, response.get_json()

    def test_summary_counts_each_status_separately(self):
        status, payload = self._list()
        self.assertEqual(status, 200)
        summary = payload['summary']
        self.assertEqual(summary['total_records'], 5)
        self.assertEqual(summary['verified_count'], 2)
        self.assertEqual(summary['recorded_count'], 1)
        self.assertEqual(summary['flagged_count'], 1)
        self.assertEqual(summary['isolated_count'], 1)
        self.assertEqual(summary['verifiedEntries'], 2)
        self.assertEqual(summary['pendingEntries'], 1)
        self.assertAlmostEqual(summary['total_volume'], 33.0)

    def test_status_filter_narrows_list_and_summary(self):
        for value, expected in (('VERIFIED', 2), ('verified', 2), ('RECORDED', 1), ('flagged', 1), ('Isolated', 1)):
            status, payload = self._list(f'?status={value}')
            self.assertEqual(status, 200, value)
            self.assertEqual(payload['meta']['total'], expected, value)
            self.assertEqual(payload['summary']['total_records'], expected, value)
            self.assertTrue(all(row['status'] == value.upper() for row in payload['items']), value)

    def test_anomaly_filter_still_works(self):
        status, payload = self._list('?status=anomaly')
        self.assertEqual(status, 200)
        self.assertEqual(payload['meta']['total'], 2)

    def test_unknown_status_is_rejected_with_field_reason(self):
        status, payload = self._list('?status=pending')
        self.assertEqual(status, 400)
        self.assertEqual(payload['code'], 'VALIDATION_ERROR')
        self.assertEqual(payload['fields'], {'status': 'invalid'})

    def test_status_filter_applies_to_production_totals(self):
        for path in ('/api/production/summary?period=month', '/api/production/group-totals?levels=month'):
            response = self.client.get(f'{path}&status=VERIFIED')
            self.assertEqual(response.status_code, 200, (path, response.get_json()))
            response = self.client.get(f'{path}&status=nope')
            self.assertEqual(response.status_code, 400, path)
            self.assertEqual(response.get_json()['fields'], {'status': 'invalid'})

    def test_rows_carry_session_date_status_and_recorded_via(self):
        _, payload = self._list()
        for row in payload['items']:
            self.assertIn(row['session'], ('Morning', 'Midday', 'Evening'))
            self.assertTrue(row['milkingDate'])
            self.assertTrue(row['status'])
            self.assertIn(row['recorded_via'], ('app', 'whatsapp', 'import'))
        self.assertEqual(sorted(row['recorded_via'] for row in payload['items']).count('whatsapp'), 1)

    def test_session_is_stored_in_canonical_form(self):
        response = self.client.post('/api/production/yield', data=json.dumps(
            {'cow_id': self.cow.id, 'amount': 7, 'session': 'midday', 'milking_date': '2026-10-01'}),
            content_type='application/json')
        self.assertEqual(response.status_code, 201, response.get_json())
        self.assertEqual(response.get_json()['session'], 'Midday')
        self.assertEqual(response.get_json()['recorded_via'], 'app')

    def test_unknown_session_is_rejected(self):
        response = self.client.post('/api/production/yield', data=json.dumps(
            {'cow_id': self.cow.id, 'amount': 7, 'session': 'night'}), content_type='application/json')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()['fields'], {'session': 'invalid'})

        log_id = self._list()[1]['items'][0]['id']
        response = self.client.patch(f'/api/production/yield/{log_id}', data=json.dumps({'session': 'night'}),
                                     content_type='application/json')
        self.assertEqual(response.status_code, 400)
        response = self.client.patch(f'/api/production/yield/{log_id}', data=json.dumps({'session': 'EVENING'}),
                                     content_type='application/json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()['session'], 'Evening')


class StatementRouteDisabledTestCase(BaseTestCase):

    def test_phone_number_no_longer_opens_a_statement(self):
        from app.models.finance import Customer
        db.session.add(Customer(tenant_id=self.tenant.id, name='Kiosk', phone_number='254700000001'))
        db.session.commit()
        for token in ('254700000001', 'anything'):
            response = self.client.get(f'/statements/{token}')
            self.assertEqual(response.status_code, 404)
            self.assertEqual(response.get_json(), {'code': 'STATEMENT_LINK_INVALID', 'error': 'This statement link is not valid.'})
