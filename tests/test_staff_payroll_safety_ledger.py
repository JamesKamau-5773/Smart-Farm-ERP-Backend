"""Staff offboarding, advances, statutory payroll, milk safety and ledger corrections."""
from __future__ import annotations

import io
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from app import db
from app.models.finance import Transaction, TransactionAttachment, TransactionStatus
from app.models.hr import Employee, EmployeeLoanMovement
from app.models.livestock import Cow, MedicalRecord
from app.models.user import Role, User
from app.services.kenya_statutory_deductions import KenyaStatutoryDeductions
from app.services.payroll_line_calculator import PayLineInput, PayrollLineCalculator
from app.utils.user_display import display_name
from tests.base import BaseTestCase

PNG = b'\x89PNG\r\n\x1a\n' + b'\x00' * 64


def test_statutory_deductions_for_a_typical_salary():
    pay = KenyaStatutoryDeductions.calculate(Decimal('30000'), date(2026, 6, 1))
    assert pay.rates_version == 'KE-2026-02'
    assert (pay.nssf_employee, pay.shif, pay.housing_levy_employee) == (Decimal('1800.00'), Decimal('825.00'), Decimal('450.00'))
    assert pay.taxable_pay == Decimal('26925.00')
    # 10% of 24,000 + 25% of 2,925, less 2,400 personal relief.
    assert pay.paye == Decimal('731.25')
    assert (pay.nssf_employer, pay.housing_levy_employer) == (Decimal('1800.00'), Decimal('450.00'))


def test_low_pay_owes_no_paye_and_shif_has_a_minimum():
    pay = KenyaStatutoryDeductions.calculate(Decimal('10000'), date(2026, 6, 1))
    assert pay.paye == Decimal('0.00')
    assert pay.shif == Decimal('300.00')


def test_nssf_follows_the_schedule_in_force_for_the_period():
    assert KenyaStatutoryDeductions.calculate(Decimal('200000'), date(2026, 6, 1)).nssf_employee == Decimal('6480.00')
    assert KenyaStatutoryDeductions.calculate(Decimal('200000'), date(2026, 1, 1)).nssf_employee == Decimal('4320.00')


def test_advance_recovery_never_eats_into_statutory_deductions():
    line = PayrollLineCalculator.calculate(PayLineInput(
        base_salary=Decimal('15000'), period_start=date(2026, 6, 1), month_days=30, leave_days=0, absence_days=0,
        loan_balance=Decimal('50000'), monthly_deduction=Decimal('50000'), statutory_enabled=True,
    ))
    assert line.statutory.employee_total > 0
    assert line.advance_deduction == Decimal('15000') - line.statutory.employee_total
    assert line.net_pay == Decimal('0.00')


def test_final_month_is_paid_for_days_employed():
    line = PayrollLineCalculator.calculate(PayLineInput(
        base_salary=Decimal('30000'), period_start=date(2026, 6, 1), month_days=30, leave_days=0, absence_days=0,
        loan_balance=Decimal('0'), monthly_deduction=Decimal('0'), statutory_enabled=False, days_paid=10,
    ))
    assert (line.gross_pay, line.net_pay) == (Decimal('10000.00'), Decimal('10000.00'))


class StaffPayrollTestCase(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.headers = self.get_auth_headers()

    def _staff(self, **fields):
        payload = {'full_name': 'Jane Worker', 'hire_date': '2025-01-01', 'base_salary': 30000, **fields}
        response = self.client.post('/api/hr/staff', json=payload, headers=self.headers)
        self.assertEqual(response.status_code, 201, response.get_json())
        return response.get_json()['id']

    def _advance(self, staff_id, amount, **extra):
        return self.client.post(f'/api/hr/staff/{staff_id}/advances', json={'amount': amount, **extra}, headers=self.headers)

    def _run(self, year=2026, month=6):
        response = self.client.post('/api/hr/payroll/runs', json={'payroll_year': year, 'payroll_month': month}, headers=self.headers)
        self.assertEqual(response.status_code, 200, response.get_json())
        return response.get_json()

    def test_advances_add_up_on_the_server_and_are_expensed(self):
        staff_id = self._staff()
        self.assertEqual(self._advance(staff_id, 1000).status_code, 201)
        second = self._advance(staff_id, 500, note='Transport')
        self.assertEqual(second.get_json()['loan_balance'], 1500.0)

        history = self.client.get(f'/api/hr/staff/{staff_id}/advances', headers=self.headers).get_json()
        self.assertEqual([m['amount'] for m in history['movements']], [500.0, 1000.0])
        ledger = Transaction.query.filter_by(source_document_type='EMPLOYEE_ADVANCE').all()
        self.assertEqual(sorted(float(entry.amount) for entry in ledger), [500.0, 1000.0])

        no_expense = self._advance(staff_id, 200, record_expense=False)
        self.assertIsNone(no_expense.get_json()['movement']['ledger_transaction_id'])

    def test_balance_cannot_be_overwritten_and_repayments_are_bounded(self):
        staff_id = self._staff()
        self._advance(staff_id, 1000)
        patched = self.client.patch(f'/api/hr/staff/{staff_id}', json={'loan_balance': 0}, headers=self.headers)
        self.assertEqual((patched.status_code, patched.get_json()['code']), (400, 'BALANCE_CHANGE_REQUIRES_ADVANCE'))
        unchanged = self.client.patch(f'/api/hr/staff/{staff_id}', json={'loan_balance': 1000}, headers=self.headers)
        self.assertEqual(unchanged.status_code, 200)

        too_much = self.client.post(f'/api/hr/staff/{staff_id}/advance-repayments', json={'amount': 5000}, headers=self.headers)
        self.assertEqual((too_much.status_code, too_much.get_json()['code']), (400, 'VALIDATION_ERROR'))
        repaid = self.client.post(f'/api/hr/staff/{staff_id}/advance-repayments', json={'amount': 1000}, headers=self.headers)
        self.assertEqual(repaid.get_json()['loan_balance'], 0.0)

    def test_payroll_run_applies_statutory_deductions_and_posts_both_ledger_entries(self):
        staff_id = self._staff(monthly_deduction=2000)
        self._advance(staff_id, 5000, record_expense=False)
        run = self._run()
        [line] = run['lineItems']
        self.assertEqual((line['paye'], line['nssf_employee'], line['shif'], line['housing_levy_employee']), (731.25, 1800.0, 825.0, 450.0))
        self.assertEqual(line['advance_deduction'], 2000.0)
        self.assertEqual(line['net_pay'], 30000 - 1800 - 825 - 450 - 731.25 - 2000)
        self.assertEqual(run['run']['total_employer_contributions'], 2250.0)

        finalized = self.client.post('/api/hr/payroll/runs/2026-06/finalize', headers=self.headers)
        self.assertEqual(finalized.status_code, 200, finalized.get_json())
        statutory = Transaction.query.filter_by(reference_code='PAYROLL-2026-06-STATUTORY').one()
        self.assertEqual(statutory.amount, Decimal('6056.25'))  # 3,806.25 deducted + 2,250 employer

        self.client.post('/api/hr/payroll/runs/2026-06/pay', headers=self.headers)
        employee = db.session.get(Employee, staff_id)
        self.assertEqual(employee.loan_balance, Decimal('3000.00'))
        deduction = EmployeeLoanMovement.query.filter_by(kind='PAYROLL_DEDUCTION').one()
        self.assertEqual((deduction.amount, deduction.balance_after), (Decimal('2000.00'), Decimal('3000.00')))

    def test_statutory_deductions_can_be_switched_off_per_employee(self):
        self._staff(statutory_deductions_enabled=False)
        [line] = self._run()['lineItems']
        self.assertEqual((line['paye'], line['net_pay'], line['statutory_rates_version']), (0.0, 30000.0, None))

    def test_summary_lists_runs_and_the_next_period(self):
        self._staff()
        self.assertEqual(self.client.get('/api/hr/payroll/runs/summary', headers=self.headers).get_json()['runs'], [])
        self._run(2026, 6)
        summary = self.client.get('/api/hr/payroll/runs/summary', headers=self.headers).get_json()
        self.assertEqual(summary['next_period']['id'], '2026-06')  # finish the draft first
        self.assertEqual((summary['runs'][0]['id'], summary['runs'][0]['staff_count']), ('2026-06', 1))
        self.client.post('/api/hr/payroll/runs/2026-06/finalize', headers=self.headers)
        summary = self.client.get('/api/hr/payroll/runs/summary', headers=self.headers).get_json()
        self.assertEqual(summary['next_period'], {'id': '2026-07', 'payroll_year': 2026, 'payroll_month': 7, 'existing_status': None})

    def test_payslip_is_available_once_finalized(self):
        staff_id = self._staff()
        self._run()
        draft = self.client.get(f'/api/hr/payroll/runs/2026-06/payslips/{staff_id}.pdf', headers=self.headers)
        self.assertEqual((draft.status_code, draft.get_json()['code']), (409, 'PAYROLL_NOT_FINALIZED'))
        self.client.post('/api/hr/payroll/runs/2026-06/finalize', headers=self.headers)
        slip = self.client.get(f'/api/hr/payroll/runs/2026-06/payslips/{staff_id}.pdf', headers=self.headers)
        self.assertEqual(slip.status_code, 200)
        self.assertTrue(slip.data.startswith(b'%PDF'))

    def test_offboarding_is_refused_while_an_advance_is_owed(self):
        staff_id = self._staff()
        self._advance(staff_id, 1000)
        response = self.client.post(f'/api/hr/staff/{staff_id}/offboard', json={'reason': 'RESIGNED'}, headers=self.headers)
        body = response.get_json()
        self.assertEqual((response.status_code, body['code'], body['loan_balance']), (409, 'LOAN_OUTSTANDING', 1000.0))

    def test_offboarding_closes_login_and_final_pay_is_prorated(self):
        staff_id = self._staff()
        worker = self.create_user(username='worker', password='WorkerPass123', role=Role.FARM_HAND)
        employee = db.session.get(Employee, staff_id)
        employee.user_id = worker.id
        db.session.commit()
        worker_token = self.app.test_client().post('/api/auth/login', json={'username': 'worker', 'password': 'WorkerPass123'}).get_json()['access_token']

        response = self.client.post(f'/api/hr/staff/{staff_id}/offboard', json={
            'end_date': '2026-06-10', 'offboarding_reason': 'contract_ended', 'offboarding_note': 'Season over',
        }, headers=self.headers)
        self.assertEqual(response.status_code, 200, response.get_json())
        body = response.get_json()
        self.assertEqual((body['end_date'], body['offboarding_reason'], body['is_active']), ('2026-06-10', 'CONTRACT_ENDED', False))
        self.assertFalse(db.session.get(User, worker.id).is_active)
        stale = self.app.test_client().get('/api/auth/me', headers={'Authorization': f'Bearer {worker_token}'})
        self.assertEqual(stale.status_code, 401)

        [line] = self._run(2026, 6)['lineItems']
        self.assertEqual((line['days_paid'], line['gross_pay']), (10, 10000.0))
        self.assertEqual(self.client.post('/api/hr/payroll/runs', json={'payroll_year': 2026, 'payroll_month': 7},
                                          headers=self.headers).status_code, 409)

    def test_offboarding_validates_reason_and_dates(self):
        staff_id = self._staff()
        bad_reason = self.client.post(f'/api/hr/staff/{staff_id}/offboard', json={'reason': 'BORED'}, headers=self.headers)
        self.assertEqual(bad_reason.get_json()['code'], 'VALIDATION_ERROR')
        future = (date.today() + timedelta(days=30)).isoformat()
        later = self.client.post(f'/api/hr/staff/{staff_id}/offboard', json={'reason': 'RESIGNED', 'end_date': future}, headers=self.headers)
        self.assertEqual(later.status_code, 400)

    def test_delete_only_removes_records_without_history(self):
        clean_id = self._staff(full_name='Typo Entry')
        self.assertEqual(self.client.delete(f'/api/hr/staff/{clean_id}', headers=self.headers).status_code, 200)
        self.assertIsNone(db.session.get(Employee, clean_id))

        paid_id = self._staff(full_name='Paid Worker')
        self._run()
        refused = self.client.delete(f'/api/hr/staff/{paid_id}', headers=self.headers)
        body = refused.get_json()
        self.assertEqual((refused.status_code, body['code'], body['history'], body['can_offboard']), (409, 'HAS_HISTORY', ['payroll'], True))

    def test_hr_errors_carry_a_code(self):
        response = self.client.get('/api/hr/payroll/runs/2030-01', headers=self.headers)
        self.assertEqual((response.status_code, response.get_json()['code']), (404, 'NOT_FOUND'))


class MilkSafetyTestCase(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.headers = self.get_auth_headers()
        self.vet = self.create_user(username='drvet', password='VetPass123', role=Role.VET, name='Dr. Achieng')
        self.cow = Cow(tenant_id=self.tenant_id, tag_number='KE-001', name='Daisy', date_of_birth=date(2021, 1, 1), is_hardlocked=True)
        db.session.add(self.cow)
        db.session.commit()

    def _treat(self, days_ago, withdrawal_days, diagnosis):
        db.session.add(MedicalRecord(
            tenant_id=self.tenant_id, cow_id=self.cow.id, vet_id=self.vet.id, diagnosis=diagnosis,
            visit_date=datetime.now(timezone.utc) - timedelta(days=days_ago), withdrawal_days_recommended=withdrawal_days,
        ))
        db.session.commit()

    def _board(self):
        return self.client.get('/api/safety/dashboard', headers=self.headers).get_json()['items']

    def test_withdrawal_end_comes_from_the_longest_running_treatment(self):
        self._treat(days_ago=2, withdrawal_days=10, diagnosis='Mastitis')
        self._treat(days_ago=1, withdrawal_days=0, diagnosis='Hoof trim')
        [item] = self._board()
        ends_at = datetime.fromisoformat(item['withdrawal_ends_at'])
        self.assertAlmostEqual((ends_at - datetime.now(timezone.utc)).total_seconds() / 86400, 8, delta=0.01)
        self.assertEqual((item['reason'], item['vet_name'], item['withdrawal_active'], item['can_release']),
                         ('Mastitis', 'Dr. Achieng', True, False))

    def test_release_during_withdrawal_needs_an_override(self):
        self._treat(days_ago=1, withdrawal_days=5, diagnosis='Mastitis')
        blocked = self.client.put(f'/api/clinical/cows/{self.cow.id}/hardlock', json={'is_locked': False}, headers=self.headers)
        self.assertEqual((blocked.status_code, blocked.get_json()['code']), (409, 'WITHDRAWAL_ACTIVE'))
        allowed = self.client.put(f'/api/clinical/cows/{self.cow.id}/hardlock',
                                  json={'is_locked': False, 'override_reason': 'Vet confirmed clear test'}, headers=self.headers)
        self.assertEqual(allowed.status_code, 200)

    def test_hold_from_the_board_and_failed_test_places_hold(self):
        self.cow.is_hardlocked = False
        db.session.commit()
        until = (datetime.now(timezone.utc) + timedelta(hours=36)).isoformat()
        held = self.client.post('/api/safety/holds', json={'cow_id': self.cow.id, 'reason': 'Blood in milk', 'until': until},
                                headers=self.headers)
        self.assertEqual(held.status_code, 201, held.get_json())
        self.assertEqual((held.get_json()['reason'], held.get_json()['source']), ('Blood in milk', 'manual'))

        failed = self.client.post('/api/safety/milk-tests', json={
            'cow_id': self.cow.id, 'test_type': 'Antibiotic residue', 'result': 'fail',
        }, headers=self.headers).get_json()
        self.assertTrue(failed['placed_on_hold'])
        self.assertFalse(failed['hold']['can_release'])
        tests = self.client.get(f'/api/safety/cows/{self.cow.id}/milk-tests', headers=self.headers).get_json()['items']
        self.assertEqual([t['result'] for t in tests], ['FAIL'])

    def test_people_without_a_name_are_not_shown_by_phone_number(self):
        owner = self.create_user(username='254788461515', password='OwnerPass123', role=Role.FARMER)
        owner.name = None
        staff = self.create_user(username='wanjiku', password='StaffPass123', role=Role.FARM_HAND)
        staff.name = '  '
        db.session.commit()
        self.assertEqual((display_name(owner.id), display_name(staff.id), display_name(self.vet.id)),
                         ('Farm owner', 'wanjiku', 'Dr. Achieng'))

    def test_bad_hold_requests_are_rejected_with_codes(self):
        missing = self.client.post('/api/safety/holds', json={'cow_id': self.cow.id}, headers=self.headers)
        self.assertEqual((missing.status_code, missing.get_json()['code']), (400, 'VALIDATION_ERROR'))
        other = self.client.post('/api/safety/milk-tests', json={'cow_id': 99999, 'test_type': 'x', 'result': 'PASS'}, headers=self.headers)
        self.assertEqual(other.status_code, 404)


class LedgerCorrectionAndAttachmentTestCase(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.headers = self.get_auth_headers()

    def _entry(self, **payload):
        response = self.client.post('/api/finance/ledger', json=payload, headers=self.headers)
        self.assertEqual(response.status_code, 201, response.get_json())
        return response.get_json()

    def _expense(self):
        return self._entry(transaction_type='Expense', category='Transport', amount=1200, paid_to='Matatu')

    def _correct(self, transaction_id, **replacement):
        return self.client.post(f'/api/finance/transactions/{transaction_id}/corrections',
                                json={'void_reason': 'Typed wrong', 'replacement': replacement}, headers=self.headers)

    def test_categories_are_served_with_default_cost_classes(self):
        catalogue = self.client.get('/api/finance/categories', headers=self.headers).get_json()
        feed = next(c for c in catalogue['expense'] if c['value'] == 'Feed Purchase')
        self.assertEqual(feed['default_cost_class'], 'COGS')
        defaults = {c['value']: c['default_cost_class'] for c in catalogue['expense']}
        self.assertEqual((defaults['Utilities'], defaults['Labor / Wages']), ('OPERATING', 'OPERATING'))
        self.assertIn('Milk Sale', [c['value'] for c in catalogue['revenue']])
        self.assertIn('OPERATING', [c['value'] for c in catalogue['cost_classes']])

    def _ledger_rows(self):
        return self.client.get('/api/finance/ledger', headers=self.headers).get_json()['items']

    def test_correction_can_change_the_amount(self):
        entry = self._expense()
        row = next(t for t in self._ledger_rows() if t['id'] == entry['id'])
        self.assertEqual((row['amount_correctable'], row['amount_lock_reason']), (True, None))
        response = self._correct(entry['id'], amount='1500.00')
        self.assertEqual(response.status_code, 201, response.get_json())
        body = response.get_json()
        self.assertEqual((body['voided_transaction']['status'], body['replacement_transaction']['amount']), ('VOIDED', 1500.0))

    def test_income_can_be_corrected_and_its_receipt_is_reissued(self):
        income = self._entry(transaction_type='Revenue', category='Other Income', amount=800, income_source='Manure sale')
        response = self._correct(income['id'], amount=850)
        self.assertEqual(response.status_code, 201, response.get_json())
        body = response.get_json()
        self.assertEqual(body['voided_transaction']['receipt']['status'], 'VOIDED')
        self.assertEqual((body['replacement_transaction']['receipt']['status'], body['replacement_transaction']['amount']), ('ISSUED', 850.0))
        refused = self._correct(body['replacement_transaction']['id'], category='Feed Purchase')
        self.assertEqual(refused.status_code, 422)

    def test_automatic_entries_keep_their_amount(self):
        entry = db.session.get(Transaction, self._expense()['id'])
        entry.source_document_type = 'INVENTORY_MOVEMENT'
        db.session.commit()
        row = next(t for t in self._ledger_rows() if t['id'] == entry.id)
        self.assertFalse(row['amount_correctable'])
        self.assertIn('posted automatically', row['amount_lock_reason'])
        response = self._correct(entry.id, amount=999)
        self.assertEqual((response.status_code, response.get_json()['code']), (422, 'UNPROCESSABLE'))
        self.assertEqual(self._correct(entry.id, category='Utilities').status_code, 201)

    def test_receipt_photo_upload_is_private_to_the_farm(self):
        entry = self._expense()
        upload = self.client.post(f'/api/finance/transactions/{entry["id"]}/attachments',
                                  data={'file': (io.BytesIO(PNG), 'receipt.png')}, headers=self.headers,
                                  content_type='multipart/form-data')
        self.assertEqual(upload.status_code, 201, upload.get_json())
        url = upload.get_json()['url']
        download = self.client.get(url, headers=self.headers)
        self.assertEqual((download.status_code, download.data, download.headers['Cache-Control']), (200, PNG, 'private, no-store'))
        self.assertEqual(self.app.test_client().get(url).status_code, 401)

        ledger = self.client.get('/api/finance/ledger', headers=self.headers).get_json()
        listed = next(item for item in ledger['items'] if item['id'] == entry['id'])
        self.assertEqual(len(listed['attachments']), 1)

        corrected = self._correct(entry['id'], amount=1300).get_json()
        self.assertEqual(TransactionAttachment.query.filter_by(transaction_id=corrected['replacement_transaction']['id']).count(), 1)

        other_tenant = self.create_tenant(name='Other')
        db.session.commit()
        self.create_user(username='intruder', password='password', role=Role.FARMER, tenant=other_tenant)
        token = self.app.test_client().post('/api/auth/login', json={'username': 'intruder', 'password': 'password'}).get_json()['access_token']
        self.assertEqual(self.app.test_client().get(url, headers={'Authorization': f'Bearer {token}'}).status_code, 404)

    def test_disguised_files_are_rejected(self):
        entry = self._expense()
        response = self.client.post(f'/api/finance/transactions/{entry["id"]}/attachments',
                                    data={'file': (io.BytesIO(b'<script>'), 'receipt.png')}, headers=self.headers,
                                    content_type='multipart/form-data')
        self.assertEqual((response.status_code, response.get_json()['code']), (400, 'VALIDATION_ERROR'))
        self.assertEqual(db.session.get(Transaction, entry['id']).status, TransactionStatus.POSTED.value)
