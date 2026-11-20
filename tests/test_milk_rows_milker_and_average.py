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


class _MilkAverageBase(BaseTestCase):

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



class MilkRowAverageTestCase(_MilkAverageBase):

    def test_first_record_has_no_average(self):
        row = self._row(self._post(12))
        self.assertIsNone(row['avg_litres'])
        self.assertIsNone(row['vs_avg_litres'])
        self.assertFalse(row['significant_drop'])

    def test_change_uses_the_drop_rules_window_session_and_verdict(self):
        self._seed(1, 12, session='Evening')
        self._seed(2, 14, session='Evening')
        self._seed(1, 30)                    # a morning: not part of an evening's average
        self._seed(9, 40, session='Evening')  # outside the 7-day window
        log_id = self._post(9)               # 9 < 13 * 0.85 → a drop
        row = self._row(log_id)
        self.assertEqual(row['avg_litres'], 13.0)
        self.assertEqual(row['vs_avg_litres'], -4.0)
        self.assertTrue(row['significant_drop'])
        self.assertEqual(row['status'], MilkLog.STATUS_FLAGGED)
        alert = MilkDropAlert.query.filter_by(cow_id=self.cow.id).one()
        self.assertIn('evening average', alert.reason)

    def test_bigger_mornings_do_not_make_an_evening_a_drop(self):
        self._seed(1, 20)                    # mornings are bigger
        self._seed(1, 10, session='Evening')
        row = self._row(self._post(9.2))
        self.assertEqual(row['avg_litres'], 10.0)
        self.assertEqual(row['vs_avg_litres'], -0.8)
        self.assertFalse(row['significant_drop'])
        self.assertEqual(MilkDropAlert.query.count(), 0)

    def test_first_record_of_a_session_has_no_average(self):
        self._seed(1, 20)
        row = self._row(self._post(5))
        self.assertIsNone(row['vs_avg_litres'])
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
        self._seed(1, 10, session='Evening')
        log_id = self._post(9)
        history = self.client.get(f'/api/animals/{self.cow.id}/milk-history').get_json()
        row = next(item for item in history['sessions'] if item['id'] == log_id)
        self.assertEqual(row['vs_avg_litres'], -1.0)
        detail = self.client.get(f'/api/production/yield/{log_id}').get_json()
        row = next(item for item in detail['sessions'] if item['id'] == log_id)
        self.assertEqual(row['vs_avg_litres'], -1.0)


class MilkRecordCorrectionTestCase(_MilkAverageBase):
    """A corrected record is judged again, so its flag, status and alert agree with it."""

    def _patch(self, log_id, **body):
        response = self.client.patch(f'/api/production/yield/{log_id}', data=json.dumps(body),
                                     content_type='application/json')
        self.assertEqual(response.status_code, 200, response.get_json())
        return response.get_json()

    def test_correcting_a_typo_clears_the_drop_and_closes_the_alert(self):
        self._seed(1, 12, session='Evening')
        log_id = self._post(1.2)                       # typo for 12
        self.assertEqual(MilkDropAlert.query.one().status, 'OPEN')
        body = self._patch(log_id, amount=12)
        self.assertEqual(body['status'], MilkLog.STATUS_RECORDED)
        self.assertFalse(body['significant_drop'])
        alert = MilkDropAlert.query.one()
        self.assertEqual(alert.status, 'RESOLVED')
        self.assertEqual(alert.investigated_by, self.farmer.id)

    def test_correcting_into_a_drop_raises_an_alert(self):
        self._seed(1, 12, session='Evening')
        log_id = self._post(12)
        self.assertEqual(MilkDropAlert.query.count(), 0)
        body = self._patch(log_id, amount=6)
        self.assertEqual(body['status'], MilkLog.STATUS_FLAGGED)
        self.assertTrue(body['significant_drop'])
        self.assertEqual(MilkDropAlert.query.filter_by(status='OPEN').count(), 1)

    def test_an_alert_under_investigation_is_left_alone(self):
        self._seed(1, 12, session='Evening')
        log_id = self._post(1.2)
        alert = MilkDropAlert.query.one()
        alert.status = 'INVESTIGATING'
        db.session.commit()
        self._patch(log_id, amount=12)
        self.assertEqual(MilkDropAlert.query.one().status, 'INVESTIGATING')

    def test_alert_stays_while_another_record_that_day_is_a_drop(self):
        self._seed(1, 12, session='Evening')
        self._seed(1, 20)
        evening = self._post(1.2)
        morning = self.client.post('/api/production/yield', data=json.dumps(
            {'cow_id': self.cow.id, 'amount': 5, 'session': 'Morning'}), content_type='application/json')
        self.assertTrue(morning.get_json()['anomaly_detected'])
        self.assertEqual(MilkDropAlert.query.count(), 2)
        self._patch(evening, amount=12)
        self.assertEqual(MilkDropAlert.query.filter_by(status='OPEN').count(), 2)

    def test_verified_record_keeps_its_status(self):
        self._seed(1, 12, session='Evening')
        log_id = self._post(1.2)
        self.client.patch(f'/api/production/yield/{log_id}/verify')
        body = self._patch(log_id, amount=12)
        self.assertEqual(body['status'], MilkLog.STATUS_VERIFIED)
        self.assertFalse(body['significant_drop'])

    def test_editing_only_the_milker_does_not_rejudge(self):
        self._seed(1, 12, session='Evening')
        log_id = self._post(1.2)
        self._patch(log_id, milker_id=None)
        self.assertEqual(MilkDropAlert.query.one().status, 'OPEN')
