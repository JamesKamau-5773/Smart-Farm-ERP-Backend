import json
from datetime import date

from app import db
from app.models.livestock import Cow
from app.models.user import Role
from tests.base import BaseTestCase


class HRTestCase(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.farmer = self.create_user(username='farmer', password='password', role=Role.FARMER)
        self.admin = self.create_user(username='admin', password='password', role=Role.ADMIN)
        self.cow = Cow(tag_number='COW-HR-001', date_of_birth=date(2022, 1, 1))
        db.session.add(self.cow)
        db.session.commit()

    def _login(self, username='farmer', password='password'):
        return self.client.post(
            '/api/auth/login',
            data=json.dumps(dict(username=username, password=password)),
            content_type='application/json'
        )

    def test_admin_can_access_farmer_scoped_hr_routes(self):
        self._login('admin', 'password')

        with self.client:
            staff_response = self.client.post(
                '/api/hr/staff',
                data=json.dumps(
                    dict(
                        full_name='Admin Created Staff',
                        hire_date='2026-05-01',
                        base_salary=45000,
                    )
                ),
                content_type='application/json'
            )
            self.assertEqual(staff_response.status_code, 201)

            list_response = self.client.get('/api/hr/staff')
            self.assertEqual(list_response.status_code, 200)

    def test_register_staff_and_create_payroll(self):
        self._login()

        with self.client:
            staff_response = self.client.post(
                '/api/hr/staff',
                data=json.dumps(
                    dict(
                        full_name='John Doe',
                        hire_date='2026-05-01',
                        base_salary=45000,
                        id_number='ID12345',
                        contract_type='Permanent',
                    )
                ),
                content_type='application/json'
            )
            self.assertEqual(staff_response.status_code, 201)
            staff_data = json.loads(staff_response.data.decode())
            staff_id = staff_data['id']

            payroll_response = self.client.post(
                '/api/hr/payroll',
                data=json.dumps(
                    dict(
                        staff_id=staff_id,
                        payroll_year=2026,
                        payroll_month=5,
                        base_salary=45000,
                        bonuses=2500,
                        deductions=1500,
                        payment_date='2026-05-31',
                    )
                ),
                content_type='application/json'
            )
            self.assertEqual(payroll_response.status_code, 201)
            payroll_data = json.loads(payroll_response.data.decode())
            self.assertEqual(payroll_data['net_pay'], 46000.0)

    def test_staff_detail_update_and_verify_return(self):
        self._login()

        with self.client:
            staff_response = self.client.post(
                '/api/hr/staff',
                data=json.dumps(
                    dict(
                        full_name='Leave User',
                        hire_date='2026-05-01',
                        base_salary=30000,
                        status='ON_LEAVE',
                        leave_type='Maternity Leave',
                        leave_start_date='2026-06-01',
                        expected_return_date='2026-06-10',
                        monthly_deduction=5000,
                        loan_balance=12000,
                    )
                ),
                content_type='application/json'
            )
            self.assertEqual(staff_response.status_code, 201)
            staff_id = json.loads(staff_response.data.decode())['id']

            detail_response = self.client.get(f'/api/hr/staff/{staff_id}')
            self.assertEqual(detail_response.status_code, 200)
            detail_data = json.loads(detail_response.data.decode())
            self.assertEqual(detail_data['name'], 'Leave User')
            self.assertIn('returnVerificationDecision', detail_data)

            update_response = self.client.patch(
                f'/api/hr/staff/{staff_id}',
                data=json.dumps(dict(monthly_deduction=6500, medicalNotes='Cleared for duty')),
                content_type='application/json'
            )
            self.assertEqual(update_response.status_code, 200)
            updated_data = json.loads(update_response.data.decode())
            self.assertEqual(updated_data['monthlyDeduction'], 6500.0)
            self.assertEqual(updated_data['medicalNotes'], 'Cleared for duty')

            verify_response = self.client.post(
                f'/api/hr/staff/{staff_id}/verify-return',
                data=json.dumps(dict(returned=True, note='Reported back to duty')),
                content_type='application/json'
            )
            self.assertEqual(verify_response.status_code, 200)
            verify_data = json.loads(verify_response.data.decode())
            self.assertEqual(verify_data['status'], 'ACTIVE')
            self.assertEqual(verify_data['returnVerificationDecision'], 'YES')
            self.assertEqual(verify_data['returnVerificationNote'], 'Reported back to duty')

    def test_payroll_run_returns_breakdown(self):
        self._login()

        with self.client:
            staff_response = self.client.post(
                '/api/hr/staff',
                data=json.dumps(
                    dict(
                        full_name='Payroll User',
                        hire_date='2026-05-01',
                        base_salary=30000,
                        status='ON_LEAVE',
                        leave_start_date='2026-06-01',
                        expected_return_date='2026-06-10',
                        unpaid_leave_days_this_month=3,
                        loan_balance=8000,
                        monthly_deduction=2000,
                    )
                ),
                content_type='application/json'
            )
            self.assertEqual(staff_response.status_code, 201)

            payroll_run_response = self.client.post(
                '/api/hr/payroll/runs',
                data=json.dumps(dict(payroll_year=2026, payroll_month=6)),
                content_type='application/json'
            )
            self.assertEqual(payroll_run_response.status_code, 200)
            payroll_run_data = json.loads(payroll_run_response.data.decode())
            self.assertIn('run', payroll_run_data)
            self.assertIn('lineItems', payroll_run_data)
            self.assertIn('summary', payroll_run_data)
            self.assertGreaterEqual(len(payroll_run_data['lineItems']), 1)
            line_item = payroll_run_data['lineItems'][0]
            self.assertIn('approvedLeaveDays', line_item)
            self.assertIn('overduePenaltyDays', line_item)
            self.assertIn('advanceDeduction', line_item)
            self.assertIn('grossPay', line_item)
            self.assertIn('netPay', line_item)
            self.assertIn('totalLeaveDeductions', payroll_run_data['run'])
            self.assertIn('totalOverduePenaltyDeductions', payroll_run_data['run'])
            self.assertIn('totalAdvanceDeductions', payroll_run_data['run'])
            self.assertIn('totalDeductions', payroll_run_data['run'])

    def test_staff_status_is_authoritatively_overdue_on_read(self):
        self._login()

        with self.client:
            staff_response = self.client.post(
                '/api/hr/staff',
                data=json.dumps(
                    dict(
                        full_name='Late Return Staff',
                        hire_date='2026-05-01',
                        base_salary=30000,
                        status='ON_LEAVE',
                        leave_start_date='2026-06-01',
                        expected_return_date='2026-06-10',
                    )
                ),
                content_type='application/json'
            )
            self.assertEqual(staff_response.status_code, 201)
            staff_id = json.loads(staff_response.data.decode())['id']

            detail_response = self.client.get(f'/api/hr/staff/{staff_id}')
            self.assertEqual(detail_response.status_code, 200)
            detail_data = json.loads(detail_response.data.decode())
            self.assertEqual(detail_data['status'], 'OVERDUE')

    def test_list_staff_and_payroll(self):
        self._login()

        with self.client:
            staff_response = self.client.post(
                '/api/hr/staff',
                data=json.dumps(dict(full_name='Jane Doe', hire_date='2026-05-01', base_salary=30000)),
                content_type='application/json'
            )
            staff_id = json.loads(staff_response.data.decode())['id']
            self.client.post(
                '/api/hr/payroll',
                data=json.dumps(dict(staff_id=staff_id, payroll_year=2026, payroll_month=5, base_salary=30000, payment_date='2026-05-31')),
                content_type='application/json'
            )

            list_staff_response = self.client.get('/api/hr/staff')
            self.assertEqual(list_staff_response.status_code, 200)
            self.assertGreaterEqual(len(json.loads(list_staff_response.data.decode())), 1)

            list_payroll_response = self.client.get('/api/hr/payroll')
            self.assertEqual(list_payroll_response.status_code, 200)
            self.assertGreaterEqual(len(json.loads(list_payroll_response.data.decode())), 1)

    def test_hr_alias_routes_work(self):
        self._login()

        with self.client:
            staff_response = self.client.post(
                '/api/hr/employees',
                data=json.dumps(dict(full_name='Alias User', hire_date='2026-05-01', base_salary=25000)),
                content_type='application/json'
            )
            self.assertEqual(staff_response.status_code, 201)
            staff_id = json.loads(staff_response.data.decode())['id']

            payroll_response = self.client.post(
                '/api/hr/payroll-records',
                data=json.dumps(dict(staff_id=staff_id, payroll_year=2026, payroll_month=5, base_salary=25000, payment_date='2026-05-31')),
                content_type='application/json'
            )
            self.assertEqual(payroll_response.status_code, 201)

            alias_staff_list = self.client.get('/api/hr/employees')
            self.assertEqual(alias_staff_list.status_code, 200)

            alias_payroll_list = self.client.get('/api/hr/payroll-records')
            self.assertEqual(alias_payroll_list.status_code, 200)
