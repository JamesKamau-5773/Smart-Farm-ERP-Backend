"""The profile page's API: who I am (GET /api/auth/me), editing it (PATCH), and changing my password."""
from datetime import date

from app import db
from app.models.audit import AuditLog
from app.models.hr import Employee
from app.models.user import Role
from tests.auth_helpers import AuthFlowMixin
from tests.base import BaseTestCase

NEW_PASSWORD = 'Kahawa-Shamba-2026'


class ProfileTestCase(AuthFlowMixin, BaseTestCase):

    def setUp(self):
        super().setUp()
        self.user = self.make_user(username='jane', phone='+254712345678', email='jane@example.com',
                                   role=Role.FARM_HAND)
        # Bearer tokens only: a cookie jar would carry the newest session and mask a revoked header.
        self.api = self.app.test_client(use_cookies=False)

    def bearer(self, login, password, **kwargs):
        return super().bearer(login, password, client=self.api, **kwargs)

    def login(self, login, password, **kwargs):
        kwargs.setdefault('client', self.api)
        return super().login(login, password, **kwargs)

    def _change(self, headers, **body):
        return self.api.post('/api/auth/password', json=body, headers=headers)

    def test_me_describes_role_membership_and_staff_record(self):
        db.session.add(Employee(tenant_id=self.tenant.id, user_id=self.user.id, full_name='Jane Wanjiru',
                                role='Milker', hire_date=date(2025, 3, 1), base_salary=15000))
        db.session.commit()
        data = self.api.get('/api/auth/me', headers=self.bearer('jane', 'OwnerPass123')).get_json()
        self.assertEqual(data['role_label'], 'Farm hand')
        self.assertTrue(data['member_since'])
        self.assertEqual(data['staff_profile']['job_title'], 'Milker')
        self.assertEqual(data['staff_profile']['hire_date'], '2025-03-01')
        self.assertNotIn('base_salary', data['staff_profile'])

    def test_me_without_staff_record(self):
        data = self.api.get('/api/auth/me', headers=self.bearer('jane', 'OwnerPass123')).get_json()
        self.assertIsNone(data['staff_profile'])

    def test_overlong_profile_fields_are_field_errors(self):
        headers = self.bearer('jane', 'OwnerPass123')
        response = self.api.patch('/api/auth/me', json={'name': 'x' * 121, 'farm_location': 'y' * 151},
                                     headers=headers)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()['fields'], {'name': 'too_long', 'farm_location': 'too_long'})

    def test_change_password_signs_out_other_sessions_and_keeps_this_one(self):
        other_session = self.bearer('jane', 'OwnerPass123', ip='10.0.0.9')
        headers = self.bearer('jane', 'OwnerPass123')
        response = self._change(headers, current_password='OwnerPass123', new_password=NEW_PASSWORD,
                                confirm_password=NEW_PASSWORD)
        self.assertEqual(response.status_code, 200, response.get_json())
        fresh = {'Authorization': f"Bearer {response.get_json()['access_token']}"}

        self.assertEqual(self.api.get('/api/auth/me', headers=fresh).status_code, 200)
        self.assertEqual(self.api.get('/api/auth/me', headers=other_session).status_code, 401)
        self.assertEqual(self.api.get('/api/auth/me', headers=headers).status_code, 401)
        self.assertEqual(self.login('jane', 'OwnerPass123', ip='10.0.0.3').status_code, 401)
        self.assertEqual(self.login('jane', NEW_PASSWORD, ip='10.0.0.4').status_code, 200)
        self.assertEqual(AuditLog.query.filter_by(action='CHANGE_PASSWORD', user_id=self.user.id).count(), 1)

    def test_wrong_current_password_is_refused_and_audited(self):
        headers = self.bearer('jane', 'OwnerPass123')
        response = self._change(headers, current_password='nope', new_password=NEW_PASSWORD,
                                confirm_password=NEW_PASSWORD)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()['code'], 'INVALID_CURRENT_PASSWORD')
        self.assertEqual(response.get_json()['fields'], {'current_password': 'invalid'})
        self.assertEqual(AuditLog.query.filter_by(action='CHANGE_PASSWORD_FAILED').count(), 1)
        self.assertEqual(self.api.get('/api/auth/me', headers=headers).status_code, 200)

    def test_validation_errors_name_the_field(self):
        headers = self.bearer('jane', 'OwnerPass123')
        cases = (
            ({'new_password': NEW_PASSWORD, 'confirm_password': NEW_PASSWORD}, {'current_password': 'required'}),
            ({'current_password': 'OwnerPass123'}, {'new_password': 'required'}),
            ({'current_password': 'OwnerPass123', 'new_password': NEW_PASSWORD, 'confirm_password': 'other'},
             {'confirm_password': 'mismatch'}),
            ({'current_password': 'OwnerPass123', 'new_password': 'OwnerPass123',
              'confirm_password': 'OwnerPass123'}, {'new_password': 'unchanged'}),
        )
        for body, fields in cases:
            response = self._change(headers, **body)
            self.assertEqual(response.status_code, 400, body)
            self.assertEqual(response.get_json()['fields'], fields, body)

    def test_weak_password_uses_the_password_policy(self):
        headers = self.bearer('jane', 'OwnerPass123')
        response = self._change(headers, current_password='OwnerPass123', new_password='short',
                                confirm_password='short')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()['code'], 'WEAK_PASSWORD')

    def test_google_only_account_can_set_a_password_without_a_current_one(self):
        headers = self.bearer('jane', 'OwnerPass123')
        self.user.set_unusable_password()
        db.session.commit()
        response = self._change(headers, new_password=NEW_PASSWORD, confirm_password=NEW_PASSWORD)
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(response.get_json()['message'], 'Password set.')
        db.session.refresh(self.user)
        self.assertTrue(self.user.has_password)
        self.assertEqual(AuditLog.query.filter_by(action='SET_PASSWORD').count(), 1)

    def test_forced_reset_goes_through_its_own_flow(self):
        headers = self.bearer('jane', 'OwnerPass123')
        self.user.requires_password_reset = True
        db.session.commit()
        response = self._change(headers, current_password='OwnerPass123', new_password=NEW_PASSWORD,
                                confirm_password=NEW_PASSWORD)
        # The reset gate answers first; the endpoint refuses too if it is ever reached.
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.get_json()['code'], 'PASSWORD_RESET_REQUIRED')
