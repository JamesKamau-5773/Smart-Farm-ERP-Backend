import json
from datetime import date

from app import db
from app.models.livestock import Cow
from app.models.user import Role, User
from app.models.hr import Employee, PayrollRun
from app.models.finance import Transaction, TransactionCategory, TransactionType
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

    def test_payroll_run_requires_registered_employees(self):
        self._login()

        response = self.client.post(
            '/api/hr/payroll/runs',
            data=json.dumps(dict(payroll_year=2026, payroll_month=9)),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(
            json.loads(response.data.decode())['error'],
            'Cannot generate payroll because no employees are registered.',
        )
        self.assertIsNone(PayrollRun.query.first())

    def test_payroll_run_rebuilds_existing_empty_draft(self):
        self._login()
        staff_response = self.client.post(
            '/api/hr/staff',
            data=json.dumps(dict(full_name='Payroll User', hire_date='2026-09-01', base_salary=7000)),
            content_type='application/json',
        )
        self.assertEqual(staff_response.status_code, 201)
        empty_run = PayrollRun(tenant_id=self.farmer.tenant_id, payroll_year=2026, payroll_month=9)
        db.session.add(empty_run)
        db.session.commit()

        response = self.client.post(
            '/api/hr/payroll/runs',
            data=json.dumps(dict(payroll_year=2026, payroll_month=9)),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.data.decode())
        self.assertEqual(payload['run']['staffCount'], 1)
        self.assertEqual(payload['lineItems'][0]['staffName'], 'Payroll User')
        self.assertEqual(payload['lineItems'][0]['baseSalary'], 7000.0)
        self.assertEqual(PayrollRun.query.count(), 1)

    def test_empty_payroll_run_cannot_be_finalized(self):
        self._login()
        empty_run = PayrollRun(tenant_id=self.farmer.tenant_id, payroll_year=2026, payroll_month=9)
        db.session.add(empty_run)
        db.session.commit()

        response = self.client.post('/api/hr/payroll/runs/2026-09/finalize')

        self.assertEqual(response.status_code, 409)
        self.assertEqual(
            json.loads(response.data.decode())['error'],
            'Cannot finalize a payroll run with no employees.',
        )
        self.assertEqual(empty_run.status, 'Draft')

    def test_finalized_legacy_payroll_reconciles_missing_ledger_expense(self):
        self._login()
        staff_response = self.client.post(
            '/api/hr/staff',
            data=json.dumps(dict(full_name='Legacy Payroll User', hire_date='2026-09-01', base_salary=7000)),
            content_type='application/json',
        )
        self.assertEqual(staff_response.status_code, 201)
        create_response = self.client.post(
            '/api/hr/payroll/runs',
            data=json.dumps(dict(payroll_year=2026, payroll_month=9)),
            content_type='application/json',
        )
        self.assertEqual(create_response.status_code, 200)
        run = PayrollRun.query.one()
        run.status = 'Finalized'
        run.farm_id = None
        db.session.commit()

        response = self.client.post('/api/hr/payroll/runs/2026-09/finalize')

        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.data.decode())
        self.assertTrue(payload['ledger_posted'])
        transaction = Transaction.query.filter_by(reference_code='PAYROLL-2026-09').one()
        self.assertIsNotNone(payload['run']['farmId'])
        self.assertEqual(transaction.farm_id, payload['run']['farmId'])
        self.assertEqual(float(transaction.amount), 7000.0)

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

    def test_farmer_can_invite_registered_employee_to_farm_account(self):
        self._login()
        staff_response = self.client.post(
            '/api/hr/staff',
            json={
                'full_name': 'Jane Farmhand',
                'phone_number': '0712345678',
                'hire_date': '2026-09-01',
                'base_salary': 25000,
                'role': 'Farmhand',
            },
        )
        self.assertEqual(staff_response.status_code, 201)
        staff_id = staff_response.get_json()['id']

        invite_response = self.client.post(
            f'/api/hr/staff/{staff_id}/account-invite',
            json={'role': Role.FARM_HAND},
        )

        self.assertEqual(invite_response.status_code, 201)
        invite = invite_response.get_json()
        self.assertEqual(invite['account']['role'], Role.FARM_HAND)
        self.assertFalse(invite['account']['is_active'])

        claim_response = self.client.post(
            '/api/auth/claim-account',
            json={'token': invite['invite_token'], 'password': 'FarmhandPass123'},
        )
        self.assertEqual(claim_response.status_code, 200)
        self.assertEqual(claim_response.get_json()['role'], Role.FARM_HAND)

        employee = Employee.query.one()
        account = User.query.filter_by(username='254712345678').one()
        self.assertEqual(employee.user_id, account.id)
        self.assertTrue(account.is_active)

    def test_staff_invite_rejects_privileged_and_cross_tenant_accounts(self):
        self._login()
        staff_response = self.client.post(
            '/api/hr/staff',
            json={'full_name': 'Local Worker', 'hire_date': '2026-09-01', 'base_salary': 10000},
        )
        staff_id = staff_response.get_json()['id']

        privileged_response = self.client.post(
            f'/api/hr/staff/{staff_id}/account-invite',
            json={'role': Role.SUPER_ADMIN, 'phone_number': '0712000001'},
        )
        self.assertEqual(privileged_response.status_code, 400)

        other_tenant = self.create_tenant(name='Other Farm')
        other_employee = Employee(
            tenant_id=other_tenant.id,
            full_name='Other Worker',
            hire_date=date(2026, 9, 1),
            base_salary=10000,
        )
        db.session.add(other_employee)
        db.session.commit()
        cross_tenant_response = self.client.post(
            f'/api/hr/staff/{other_employee.id}/account-invite',
            json={'role': Role.FARM_HAND, 'phone_number': '0712000002'},
        )
        self.assertEqual(cross_tenant_response.status_code, 404)

    def test_staffing_recommendations_are_advisory_and_headcount_based(self):
        self._login()
        for index in range(6):
            db.session.add(Employee(
                tenant_id=self.farmer.tenant_id,
                full_name=f'Worker {index}',
                hire_date=date(2026, 9, 1),
                base_salary=10000,
            ))
        db.session.commit()

        response = self.client.get('/api/hr/staffing-recommendations')

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload['employee_count'], 6)
        self.assertEqual(payload['farm_size'], 'GROWING')
        self.assertEqual(payload['recommended_roles']['FARM_SUPERVISOR'], 1)
        self.assertTrue(payload['advisory_only'])

    def test_onboarding_invite_links_employee_and_sets_pending_status(self):
        self._login()
        employee = Employee(
            tenant_id=self.farmer.tenant_id,
            full_name='Invited Supervisor',
            phone_number='0712345001',
            hire_date=date(2026, 9, 1),
            base_salary=30000,
        )
        db.session.add(employee)
        db.session.commit()

        response = self.client.post(
            '/api/onboarding/invite',
            json={'employee_id': employee.id, 'role': Role.FARM_SUPERVISOR},
        )

        self.assertEqual(response.status_code, 201)
        payload = response.get_json()
        self.assertEqual(payload['expires_in_hours'], 48)
        self.assertTrue(payload['claim_url'])
        db.session.refresh(employee)
        self.assertEqual(employee.onboarding_status, 'INVITE_PENDING')
        self.assertIsNotNone(employee.user_id)
        self.assertEqual(employee.user.role, Role.FARM_SUPERVISOR)
        self.assertFalse(employee.user.is_active)

    def test_reissuing_onboarding_invite_invalidates_previous_token(self):
        self._login()
        employee = Employee(
            tenant_id=self.farmer.tenant_id,
            full_name='Reinvited Worker',
            phone_number='0712345003',
            hire_date=date(2026, 9, 1),
            base_salary=20000,
        )
        db.session.add(employee)
        db.session.commit()

        first = self.client.post(
            '/api/onboarding/invite',
            json={'employee_id': employee.id, 'role': Role.FARM_HAND},
        ).get_json()
        second_response = self.client.post(
            '/api/onboarding/invite',
            json={'employee_id': employee.id, 'role': Role.FARM_SUPERVISOR},
        )
        self.assertEqual(second_response.status_code, 200)
        second = second_response.get_json()

        stale_claim = self.client.post(
            '/api/auth/claim-account',
            json={'token': first['invite_token'], 'password': 'PermanentPass123'},
        )
        self.assertEqual(stale_claim.status_code, 400)

        current_claim = self.client.post(
            '/api/auth/claim-account',
            json={'token': second['invite_token'], 'password': 'PermanentPass123'},
        )
        self.assertEqual(current_claim.status_code, 200)
        self.assertEqual(current_claim.get_json()['role'], Role.FARM_SUPERVISOR)

    def test_provisioned_employee_is_forced_to_reset_password(self):
        self._login()
        employee = Employee(
            tenant_id=self.farmer.tenant_id,
            full_name='Provisioned Farmhand',
            phone_number='0712345002',
            hire_date=date(2026, 9, 1),
            base_salary=20000,
        )
        db.session.add(employee)
        db.session.commit()

        provision_response = self.client.post(
            '/api/onboarding/provision',
            json={
                'employee_id': employee.id,
                'role': Role.FARM_HAND,
                'password': 'TemporaryPass123',
            },
        )
        self.assertEqual(provision_response.status_code, 201)
        self.assertTrue(provision_response.get_json()['account']['requires_password_reset'])

        worker_client = self.app.test_client()
        login_response = worker_client.post(
            '/api/auth/login',
            json={'username': '254712345002', 'password': 'TemporaryPass123'},
        )
        self.assertEqual(login_response.status_code, 200)
        self.assertTrue(login_response.get_json()['requires_password_reset'])
        restricted_token = login_response.get_json()['access_token']

        me_response = worker_client.get('/api/auth/me')
        self.assertEqual(me_response.status_code, 200)
        self.assertTrue(me_response.get_json()['requires_password_reset'])

        blocked_response = worker_client.patch('/api/auth/me', json={'name': 'Blocked Change'})
        self.assertEqual(blocked_response.status_code, 403)
        self.assertEqual(blocked_response.get_json()['code'], 'PASSWORD_RESET_REQUIRED')

        mismatch_response = worker_client.post(
            '/api/auth/change-password',
            json={'password': 'PermanentPass123', 'confirm_password': 'DifferentPass123'},
        )
        self.assertEqual(mismatch_response.status_code, 400)

        reset_response = worker_client.post(
            '/api/auth/change-password',
            json={'password': 'PermanentPass123', 'confirm_password': 'PermanentPass123'},
        )
        self.assertEqual(reset_response.status_code, 200)
        self.assertFalse(reset_response.get_json()['requires_password_reset'])

        revoked_token_response = self.app.test_client().get(
            '/api/auth/me',
            headers={'Authorization': f'Bearer {restricted_token}'},
        )
        self.assertEqual(revoked_token_response.status_code, 401)

        allowed_response = worker_client.patch('/api/auth/me', json={'name': 'Allowed Change'})
        self.assertEqual(allowed_response.status_code, 200)
        db.session.refresh(employee)
        self.assertEqual(employee.onboarding_status, 'ACTIVE')

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

    def test_payroll_run_is_immutable_and_payment_is_idempotent(self):
        self._login()

        with self.client:
            staff_response = self.client.post(
                '/api/hr/staff',
                data=json.dumps(dict(
                    full_name='Immutable Payroll User',
                    hire_date='2026-05-01',
                    base_salary=30000,
                    loan_balance=8000,
                    monthly_deduction=2000,
                )),
                content_type='application/json',
            )
            self.assertEqual(staff_response.status_code, 201)
            staff_id = json.loads(staff_response.data.decode())['id']

            create_response = self.client.post(
                '/api/hr/payroll/runs',
                data=json.dumps(dict(payroll_year=2026, payroll_month=7)),
                content_type='application/json',
            )
            self.assertEqual(create_response.status_code, 200)
            created = json.loads(create_response.data.decode())
            self.assertEqual(created['run']['status'], 'Draft')
            self.assertEqual(created['lineItems'][0]['baseSalary'], 30000.0)

            update_response = self.client.patch(
                f'/api/hr/staff/{staff_id}',
                data=json.dumps(dict(base_salary=50000)),
                content_type='application/json',
            )
            self.assertEqual(update_response.status_code, 200)

            read_response = self.client.get('/api/hr/payroll/runs/2026-07')
            self.assertEqual(read_response.status_code, 200)
            self.assertEqual(json.loads(read_response.data.decode())['lineItems'][0]['baseSalary'], 30000.0)

            premature_payment = self.client.post('/api/hr/payroll/runs/2026-07/pay')
            self.assertEqual(premature_payment.status_code, 409)

            finalize_response = self.client.post('/api/hr/payroll/runs/2026-07/finalize')
            self.assertEqual(finalize_response.status_code, 200)
            self.assertEqual(json.loads(finalize_response.data.decode())['run']['status'], 'Finalized')
            payroll_expense = Transaction.query.filter_by(reference_code='PAYROLL-2026-07').one()
            self.assertEqual(payroll_expense.transaction_type, TransactionType.EXPENSE)
            self.assertEqual(payroll_expense.category, TransactionCategory.LABOR_WAGES)
            self.assertEqual(float(payroll_expense.amount), 28000.0)

            ledger_response = self.client.get('/api/finance/ledger')
            self.assertEqual(ledger_response.status_code, 200)
            self.assertEqual(json.loads(ledger_response.data.decode())['summary']['total_costs'], 28000.0)

            duplicate_finalize = self.client.post('/api/hr/payroll/runs/2026-07/finalize')
            self.assertEqual(duplicate_finalize.status_code, 200)
            self.assertEqual(Transaction.query.filter_by(reference_code='PAYROLL-2026-07').count(), 1)

            payment_response = self.client.post(
                '/api/hr/payroll/runs/2026-07/pay',
                data=json.dumps(dict(payment_reference='BANK-2026-07-001')),
                content_type='application/json',
            )
            self.assertEqual(payment_response.status_code, 200)
            self.assertEqual(json.loads(payment_response.data.decode())['run']['status'], 'Paid')

            duplicate_payment = self.client.post('/api/hr/payroll/runs/2026-07/pay')
            self.assertEqual(duplicate_payment.status_code, 200)
            employee = db.session.get(Employee, staff_id)
            self.assertEqual(float(employee.loan_balance), 6000.0)

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
