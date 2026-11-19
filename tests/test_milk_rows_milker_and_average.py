"""BR-019 item 3: milker apart from who recorded it. BR-025: change against the cow's average."""
import json
from datetime import date, datetime, timedelta, timezone

from app import db
from app.models.hr import Employee
from app.models.livestock import Cow
from app.models.supply import MilkDropAlert, MilkLog
from app.models.tenant import Tenant
from app.models.user import Role
from tests.base import BaseTestCase


class MilkRowPeopleTestCase(BaseTestCase):

    def setUp(self):
        super().setUp()
        self.farmer = self.create_user(username='farmer', password='password', role=Role.FARMER, name='Wanjiru')
        self.cow = Cow(tag_number='COW001', date_of_birth=date(2022, 1, 1))
        self.milker = Employee(tenant_id=self.tenant.id, full_name='Otieno', hire_date=date(2026, 1, 1),
                               base_salary=10000)
        db.session.add_all([self.cow, self.milker])
        db.session.commit()
        self.client.post('/api/auth/login', data=json.dumps({'username': 'farmer', 'password': 'password'}),
                         content_type='application/json')

    def _post(self, **body):
        body = {'cow_id': self.cow.id, 'amount': 10, 'session': 'Morning', **body}
        return self.client.post('/api/production/yield', data=json.dumps(body), content_type='application/json')

    def _rows(self):
        return self.client.get('/api/production/yield').get_json()['items']

    def test_named_milker_is_sent_apart_from_who_recorded_it(self):
        response = self._post(milker_id=self.milker.id)
        self.assertEqual(response.status_code, 201, response.get_json())
        row = self._rows()[0]
        self.assertEqual(row['milker_id'], self.milker.id)
        self.assertEqual(row['milker_name'], 'Otieno')
        self.assertEqual(row['recorded_by_name'], 'Wanjiru')
        self.assertEqual(row['recorded_via'], 'app')

    def test_without_a_named_milker_the_recorder_is_the_milker(self):
        self.assertEqual(self._post().status_code, 201)
        row = self._rows()[0]
        self.assertIsNone(row['milker_id'])
        self.assertEqual(row['milker_name'], 'Wanjiru')
        self.assertEqual(row['recorded_by_name'], 'Wanjiru')

    def test_milker_must_be_an_employee_of_this_farm(self):
        other = Tenant(name='Other farm')
        db.session.add(other)
        db.session.flush()
        stranger = Employee(tenant_id=other.id, full_name='Stranger', hire_date=date(2026, 1, 1), base_salary=1)
        db.session.add(stranger)
        db.session.commit()
        for value in (stranger.id, 999999, 'abc', True):
            response = self._post(milker_id=value)
            self.assertEqual(response.status_code, 400, value)
            self.assertEqual(response.get_json()['fields'], {'milker_id': 'invalid'})
        self.assertEqual(MilkLog.query.count(), 0)

    def test_milker_can_be_set_and_cleared_on_edit(self):
        log_id = self._post().get_json()['id']
        patch = lambda body: self.client.patch(f'/api/production/yield/{log_id}', data=json.dumps(body),
                                               content_type='application/json')
        self.assertEqual(patch({'milker_id': self.milker.id}).get_json()['milker_id'], self.milker.id)
        self.assertEqual(self._rows()[0]['milker_name'], 'Otieno')
        self.assertIsNone(patch({'milker_id': None}).get_json()['milker_id'])
        self.assertEqual(self._rows()[0]['milker_name'], 'Wanjiru')
        self.assertEqual(patch({'milker_id': 'x'}).status_code, 400)


class MilkRowAverageTestCase(BaseTestCase):

    def setUp(self):
        super().setUp()
        self.farmer = self.create_user(username='farmer', password='password', role=Role.FARMER)
        self.cow = Cow(tag_number='COW001', date_of_birth=date(2022, 1, 1))
        db.session.add(self.cow)
        db.session.commit()
        self.client.post('/api/auth/login', data=json.dumps({'username': 'farmer', 'password': 'password'}),
                         content_type='application/json')

    def _seed(self, days_ago, amount, session='Morning'):
        db.session.add(MilkLog(
            tenant_id=self.tenant.id, cow_id=self.cow.id, amount_liters=amount, session=session,
            recorded_by=self.farmer.id, is_saleable=True, anomaly_flag=False,
            timestamp=datetime.now(timezone.utc) - timedelta(days=days_ago),
        ))
        db.session.commit()

    def _post(self, amount):
        response = self.client.post('/api/production/yield', data=json.dumps(
            {'cow_id': self.cow.id, 'amount': amount, 'session': 'Evening'}), content_type='application/json')
        self.assertEqual(response.status_code, 201, response.get_json())
        return response.get_json()['id']

    def _row(self, log_id):
        rows = self.client.get('/api/production/yield').get_json()['items']
        return next(row for row in rows if row['id'] == log_id)

    def test_first_record_has_no_average(self):
        row = self._row(self._post(12))
        self.assertIsNone(row['avg_litres'])
        self.assertIsNone(row['vs_avg_litres'])
        self.assertFalse(row['significant_drop'])

    def test_change_uses_the_drop_rules_window_and_verdict(self):
        self._seed(1, 14)
        self._seed(2, 12, session='Evening')
        self._seed(9, 40)   # outside the 7-day window: not part of the average
        log_id = self._post(8)   # 8 < 13 * 0.85 → a drop
        row = self._row(log_id)
        self.assertEqual(row['avg_litres'], 13.0)
        self.assertEqual(row['vs_avg_litres'], -5.0)
        self.assertTrue(row['significant_drop'])
        self.assertEqual(row['status'], MilkLog.STATUS_FLAGGED)
        # The same verdict raised the milk-drop alert.
        self.assertEqual(MilkDropAlert.query.filter_by(cow_id=self.cow.id).count(), 1)

    def test_small_dip_is_not_a_significant_drop(self):
        self._seed(1, 10)
        row = self._row(self._post(9.2))
        self.assertEqual(row['vs_avg_litres'], -0.8)
        self.assertFalse(row['significant_drop'])

    def test_each_row_is_measured_against_its_own_window(self):
        self._seed(3, 10)
        self._seed(2, 20)
        self._seed(1, 30)
        rows = {row['amount']: row for row in self.client.get('/api/production/yield').get_json()['items']}
        self.assertIsNone(rows[10.0]['vs_avg_litres'])
        self.assertEqual(rows[20.0]['vs_avg_litres'], 10.0)
        self.assertEqual(rows[30.0]['avg_litres'], 15.0)
        self.assertEqual(rows[30.0]['vs_avg_litres'], 15.0)

    def test_animal_history_and_record_detail_carry_the_same_fields(self):
        self._seed(1, 10)
        log_id = self._post(9)
        history = self.client.get(f'/api/animals/{self.cow.id}/milk-history').get_json()
        row = next(item for item in history['sessions'] if item['id'] == log_id)
        self.assertEqual(row['vs_avg_litres'], -1.0)
        detail = self.client.get(f'/api/production/yield/{log_id}').get_json()
        row = next(item for item in detail['sessions'] if item['id'] == log_id)
        self.assertEqual(row['vs_avg_litres'], -1.0)
