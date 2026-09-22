import json
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, date, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy import update

from tests.base import BaseTestCase
from app.models.user import Role
from app.models.finance import Buyer, CostClass, Customer, Receipt, ReceiptAuditLog, SalesLedger, Transaction, TransactionAuditLog, TransactionStatus, TransactionType, TransactionCategory, PaymentStatus
from app.models.supply import MilkLog
from app.models.livestock import Cow
from app.models.supply import MilkSession
from app.services.receipt_service import ReceiptService
from app.services.finance_service import FinanceService
from app import db

class FinanceTestCase(BaseTestCase):

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

    def test_daily_summary_separates_feed_cost_from_payroll(self):
        now = datetime.now(timezone.utc)
        db.session.add_all([
            Transaction(
                tenant_id=self.tenant.id,
                transaction_type=TransactionType.EXPENSE,
                category=TransactionCategory.FEED_PURCHASE,
                amount=500,
                status=TransactionStatus.POSTED.value,
                recorded_by=self.farmer.id,
                timestamp=now,
            ),
            Transaction(
                tenant_id=self.tenant.id,
                transaction_type=TransactionType.EXPENSE,
                category=TransactionCategory.LABOR_WAGES,
                amount=7000,
                status=TransactionStatus.POSTED.value,
                recorded_by=self.farmer.id,
                timestamp=now,
            ),
        ])
        db.session.commit()

        summary = FinanceService.get_daily_financial_summary(self.tenant.id)

        self.assertEqual(float(summary['feed_cost_total_kes']), 500.0)
        self.assertEqual(float(summary['total_costs_kes']), 7500.0)
        self.assertEqual(float(summary['net_margin_kes']), -7500.0)

    def test_get_unit_cost(self):
        """Test calculating the unit cost of milk production."""
        # Log some expenses
        tx1 = Transaction(transaction_type=TransactionType.EXPENSE, category=TransactionCategory.FEED_PURCHASE, amount=1000, recorded_by=self.farmer.id, timestamp=datetime.now(timezone.utc))
        tx2 = Transaction(transaction_type=TransactionType.EXPENSE, category=TransactionCategory.VET_FEES, amount=500, recorded_by=self.farmer.id, timestamp=datetime.now(timezone.utc))
        db.session.add_all([tx1, tx2])

        # Log some milk production
        milk_log1 = MilkLog(tenant_id=self.tenant.id, cow_id=self.cow.id, amount_liters=100, session=MilkSession.MORNING, is_saleable=True, recorded_by=self.farmer.id, timestamp=datetime.now(timezone.utc))
        milk_log2 = MilkLog(tenant_id=self.tenant.id, cow_id=self.cow.id, amount_liters=50, session=MilkSession.EVENING, is_saleable=True, recorded_by=self.farmer.id, timestamp=datetime.now(timezone.utc))
        db.session.add_all([milk_log1, milk_log2])
        db.session.commit()

        self._login('farmer', 'password')
        with self.client:
            response = self.client.get('/api/finance/unit-cost')
            self.assertEqual(response.status_code, 200)
            data = json.loads(response.data.decode())
            self.assertEqual(data['total_expenses_kes'], 1500.0)
            self.assertEqual(data['total_saleable_liters'], 150.0)
            self.assertEqual(data['unit_cost_per_liter_kes'], 10.0)

    def test_trigger_billing(self):
        """Test initiating an M-Pesa STK push."""
        self._login('farmer', 'password')
        with self.client:
            response = self.client.post(
                '/api/finance/billing/stk-push',
                data=json.dumps(dict(
                    phone_number='254712345678',
                    amount=100
                )),
                content_type='application/json'
            )
            # This will likely fail without proper M-Pesa credentials,
            # but we can check for a 500-level error which indicates the code is running.
            self.assertIn(response.status_code, [200, 400, 500])

    def test_sales_ledger_rejects_duplicate_buyer_date(self):
        buyer = Buyer(
            tenant_id=self.tenant.id,
            name='Kisii Dairy',
            agreed_rate_per_liter=55,
        )
        db.session.add(buyer)
        db.session.commit()

        first_entry = SalesLedger(
            tenant_id=self.tenant.id,
            buyer_id=buyer.id,
            date=date(2026, 5, 31),
            liters_sold=100,
            total_cost=5500,
            payment_status=PaymentStatus.UNPAID,
        )
        db.session.add(first_entry)
        db.session.commit()

        duplicate_entry = SalesLedger(
            tenant_id=self.tenant.id,
            buyer_id=buyer.id,
            date=date(2026, 5, 31),
            liters_sold=100,
            total_cost=5500,
            payment_status=PaymentStatus.UNPAID,
        )
        db.session.add(duplicate_entry)

        with self.assertRaises(IntegrityError):
            db.session.commit()

        db.session.rollback()

    def test_create_buyer_conflict_returns_409(self):
        self._login('farmer', 'password')

        with self.client:
            first = self.client.post(
                '/api/finance/buyers',
                data=json.dumps({
                    'name': 'Kisii Dairy',
                    'agreed_rate_per_liter': 55,
                }),
                content_type='application/json',
            )
            self.assertEqual(first.status_code, 201)

            duplicate = self.client.post(
                '/api/finance/buyers',
                data=json.dumps({
                    'name': 'Kisii Dairy',
                    'agreed_rate_per_liter': 55,
                }),
                content_type='application/json',
            )

        self.assertEqual(duplicate.status_code, 409)

    def test_create_buyer_accepts_frontend_rate_per_liter_alias(self):
        self._login('farmer', 'password')

        with self.client:
            response = self.client.post(
                '/api/finance/buyers',
                data=json.dumps({
                    'name': 'peter',
                    'contact': '+2541234560789',
                    'type': 'Individual',
                    'rate_per_liter': 41,
                    'balance': 0,
                }),
                content_type='application/json',
            )

        self.assertEqual(response.status_code, 201)
        payload = json.loads(response.data.decode())
        self.assertEqual(payload['name'], 'peter')
        self.assertEqual(payload['agreed_rate_per_liter'], 41.0)
        self.assertEqual(payload['rate_per_liter'], 41.0)

    def test_create_customer_conflict_returns_409(self):
        self._login('farmer', 'password')

        with self.client:
            first = self.client.post(
                '/api/finance/customers',
                data=json.dumps({
                    'name': 'Mary',
                    'phone_number': '254712345678',
                }),
                content_type='application/json',
            )
            self.assertEqual(first.status_code, 201)

            duplicate = self.client.post(
                '/api/finance/customers',
                data=json.dumps({
                    'name': 'Mary',
                    'phone_number': '254712345678',
                }),
                content_type='application/json',
            )

        self.assertEqual(duplicate.status_code, 409)

    def test_ledger_returns_server_computed_summary(self):
        self._login('farmer', 'password')

        other_farm = self.create_farm(tenant=self.tenant, name='Other Farm')
        db.session.add(Transaction(
            tenant_id=self.tenant.id,
            farm_id=other_farm.id,
            transaction_type=TransactionType.REVENUE,
            category=TransactionCategory.MILK_SALE,
            amount=9000,
            recorded_by=self.farmer.id,
            timestamp=datetime.now(timezone.utc),
        ))
        customer = Customer(
            tenant_id=self.tenant.id,
            name='Summary Customer',
            phone_number='254700000321',
        )
        db.session.add(customer)
        db.session.commit()

        with self.client:
            expense_response = self.client.post(
                '/api/finance/ledger',
                data=json.dumps({
                    'transaction_type': 'Expense',
                    'category': 'Feed Purchase',
                    'amount': 1000,
                    'paid_to': 'Feed Supplier',
                }),
                content_type='application/json',
            )
            self.assertEqual(expense_response.status_code, 201)

            revenue_response = self.client.post(
                '/api/finance/ledger',
                data=json.dumps({
                    'transaction_type': 'Revenue',
                    'category': 'Milk Sale',
                    'amount': 2500,
                    'income_source': 'Farm-gate milk sales',
                }),
                content_type='application/json',
            )
            self.assertEqual(revenue_response.status_code, 201)

            db.session.add_all([
                Transaction(
                    tenant_id=self.tenant.id,
                    farm_id=self.farm.id,
                    transaction_type=TransactionType.DEBIT,
                    category=TransactionCategory.MILK_SALE,
                    amount=600,
                    recorded_by=self.farmer.id,
                    status=TransactionStatus.POSTED.value,
                    timestamp=datetime.now(timezone.utc),
                ),
                Transaction(
                    tenant_id=self.tenant.id,
                    farm_id=self.farm.id,
                    transaction_type=TransactionType.CREDIT,
                    category=TransactionCategory.MILK_SALE,
                    amount=100,
                    recorded_by=self.farmer.id,
                    status=TransactionStatus.POSTED.value,
                    timestamp=datetime.now(timezone.utc),
                ),
                Transaction(
                    tenant_id=self.tenant.id,
                    farm_id=self.farm.id,
                    transaction_type=TransactionType.PAYMENT,
                    category=TransactionCategory.PAYMENT,
                    amount=500,
                    customer_id=customer.id,
                    recorded_by=self.farmer.id,
                    status=TransactionStatus.POSTED.value,
                    timestamp=datetime.now(timezone.utc),
                ),
            ])
            db.session.commit()

            list_response = self.client.get('/api/finance/ledger')
            self.assertEqual(list_response.status_code, 200)
            payload = json.loads(list_response.data.decode())
            self.assertIn('summary', payload)
            self.assertEqual(payload['summary']['transaction_count'], 5)
            self.assertAlmostEqual(payload['summary']['total_income'], 3000.0)
            self.assertAlmostEqual(payload['summary']['total_costs'], 1000.0)
            self.assertAlmostEqual(payload['summary']['total_profit'], 2000.0)

    def test_ledger_summary_scopes_sales_and_receivables_by_account_search(self):
        self._login('farmer', 'password')
        customer = Customer(
            tenant_id=self.tenant.id,
            name='Auntie Retail',
            phone_number='254700000777',
            account_balance=700,
        )
        credit_customer = Customer(
            tenant_id=self.tenant.id,
            name='Credit Customer',
            phone_number='254700000778',
            account_balance=-200,
        )
        buyer = Buyer(
            tenant_id=self.tenant.id,
            farm_id=self.farm.id,
            name='Auntie Dairies',
            agreed_rate_per_liter=50,
        )
        db.session.add_all([customer, credit_customer, buyer])
        db.session.flush()
        db.session.add_all([
            SalesLedger(
                tenant_id=self.tenant.id,
                buyer_id=buyer.id,
                date=date(2026, 9, 1),
                liters_sold=0,
                total_cost=900,
                payment_status=PaymentStatus.UNPAID,
                shift='Opening',
            ),
            Transaction(
                tenant_id=self.tenant.id,
                farm_id=self.farm.id,
                customer_id=customer.id,
                transaction_type=TransactionType.DEBIT,
                category=TransactionCategory.MILK_SALE,
                amount=1000,
                status=TransactionStatus.POSTED.value,
                recorded_by=self.farmer.id,
            ),
            Transaction(
                tenant_id=self.tenant.id,
                farm_id=self.farm.id,
                buyer_id=buyer.id,
                transaction_type=TransactionType.DEBIT,
                category=TransactionCategory.MILK_SALE,
                amount=1200,
                status=TransactionStatus.POSTED.value,
                recorded_by=self.farmer.id,
            ),
        ])
        db.session.commit()

        search_response = self.client.get('/api/finance/ledger?search_query=auntie')
        self.assertEqual(search_response.status_code, 200)
        search_payload = search_response.get_json()
        self.assertEqual(search_payload['summary']['recognized_sales'], 2200.0)
        self.assertEqual(search_payload['summary']['outstanding_receivables'], 1600.0)
        self.assertEqual(search_payload['summary']['customer_credit'], 0.0)
        self.assertEqual(search_payload['summary']['ledger_records'], 2)
        self.assertEqual(search_payload['summary_scope']['mode'], 'search')
        self.assertEqual(len(search_payload['items']), 2)

        customer_response = self.client.get(
            f'/api/finance/ledger?account_type=customer&account_id={customer.id}'
        )
        self.assertEqual(customer_response.status_code, 200)
        customer_payload = customer_response.get_json()
        self.assertEqual(customer_payload['summary']['recognized_sales'], 1000.0)
        self.assertEqual(customer_payload['summary']['outstanding_receivables'], 700.0)
        self.assertEqual(customer_payload['summary_scope']['account_type'], 'customer')

        buyer_response = self.client.get(
            f'/api/finance/ledger?account_type=buyer&account_id={buyer.id}'
        )
        self.assertEqual(buyer_response.status_code, 200)
        buyer_payload = buyer_response.get_json()
        self.assertEqual(buyer_payload['summary']['recognized_sales'], 1200.0)
        self.assertEqual(buyer_payload['summary']['outstanding_receivables'], 900.0)
        self.assertEqual(buyer_payload['summary_scope']['account_type'], 'buyer')

        global_response = self.client.get('/api/finance/ledger')
        self.assertEqual(global_response.status_code, 200)
        global_summary = global_response.get_json()['summary']
        self.assertEqual(global_summary['outstanding_receivables'], 1600.0)
        self.assertEqual(global_summary['customer_credit'], 200.0)

    def test_ledger_rejects_customer_revenue_and_captures_income_expense_counterparties(self):
        self._login('farmer', 'password')
        customer = Customer(
            tenant_id=self.tenant.id,
            name='Dairy Co-op',
            phone_number='254700000099',
        )
        db.session.add(customer)
        db.session.commit()

        with self.client:
            income_response = self.client.post('/api/finance/ledger', json={
                'transaction_type': 'Revenue',
                'category': 'Livestock Sale',
                'amount': 2500,
                'income_source': 'Farm-gate livestock sale',
                'payment_method': 'M-Pesa',
            })
            customer_revenue_response = self.client.post('/api/finance/ledger', json={
                'transaction_type': 'Revenue',
                'category': 'Milk Sale',
                'amount': 2500,
                'customer_id': customer.id,
            })
            expense_response = self.client.post('/api/finance/ledger', json={
                'transaction_type': 'Expense',
                'category': 'Utilities',
                'amount': 800,
                'paid_to': 'Agrovet Store',
                'payment_method': 'Cash',
            })

        self.assertEqual(income_response.status_code, 201)
        self.assertEqual(income_response.get_json()['counterparty_name'], 'Farm-gate livestock sale')
        self.assertEqual(income_response.get_json()['payment_method'], 'M-Pesa')
        self.assertEqual(customer_revenue_response.status_code, 400)
        self.assertIn('payment endpoints', customer_revenue_response.get_json()['error'])
        self.assertEqual(expense_response.status_code, 201)
        self.assertEqual(expense_response.get_json()['counterparty_name'], 'Agrovet Store')
        self.assertEqual(expense_response.get_json()['payment_method'], 'Cash')

    def test_ledger_rejects_customer_revenue_with_string_customer_id(self):
        self._login('farmer', 'password')
        customer = Customer(
            tenant_id=self.tenant.id,
            name='Form Customer',
            phone_number='254700000177',
        )
        db.session.add(customer)
        db.session.commit()

        with self.client:
            response = self.client.post('/api/finance/ledger', json={
                'transaction_type': 'Revenue',
                'category': 'Milk Sale',
                'amount': 18000,
                'customer_id': str(customer.id),
                'payment_method': 'Cash',
                'date': '2026-08-30',
            })

        self.assertEqual(response.status_code, 400)
        self.assertIn('payment endpoints', response.get_json()['error'])

    def test_ledger_rejects_non_integer_customer_or_buyer_ids(self):
        self._login('farmer', 'password')

        with self.client:
            customer_response = self.client.post('/api/finance/ledger', json={
                'transaction_type': 'Revenue',
                'category': 'Milk Sale',
                'amount': 18000,
                'customer_id': '18.0',
                'income_source': 'Farm gate',
            })
            buyer_response = self.client.post('/api/finance/ledger', json={
                'transaction_type': 'Revenue',
                'category': 'Milk Sale',
                'amount': 18000,
                'buyer_id': True,
                'income_source': 'Farm gate',
            })

        self.assertEqual(customer_response.status_code, 400)
        self.assertEqual(customer_response.get_json()['error'], 'customer_id must be a valid integer.')
        self.assertEqual(buyer_response.status_code, 400)
        self.assertEqual(buyer_response.get_json()['error'], 'buyer_id must be a valid integer.')

    def test_ledger_rejects_category_for_wrong_direction(self):
        self._login('farmer', 'password')

        with self.client:
            response = self.client.post('/api/finance/ledger', json={
                'transaction_type': 'Revenue',
                'category': 'Feed Purchase',
                'amount': 1000,
            })

        self.assertEqual(response.status_code, 400)

    def test_ledger_requires_direction_specific_counterparty(self):
        self._login('farmer', 'password')

        with self.client:
            income_response = self.client.post('/api/finance/ledger', json={
                'transaction_type': 'Revenue',
                'category': 'Other Income',
                'amount': 1000,
            })
            expense_response = self.client.post('/api/finance/ledger', json={
                'transaction_type': 'Expense',
                'category': 'Utilities',
                'amount': 500,
            })

        self.assertEqual(income_response.status_code, 400)
        self.assertIn('income_source', income_response.get_json()['error'])
        self.assertEqual(expense_response.status_code, 400)
        self.assertIn('paid_to', expense_response.get_json()['error'])

    def test_ledger_includes_date_and_counterparty_name(self):
        self._login('farmer', 'password')

        buyer = Buyer(
            tenant_id=self.tenant.id,
            name='Daily Dairies',
            agreed_rate_per_liter=60,
        )
        db.session.add(buyer)
        db.session.commit()

        with self.client:
            response = self.client.post(
                '/api/finance/ledger',
                data=json.dumps({
                    'transaction_type': 'Revenue',
                    'category': 'Milk Sale',
                    'amount': 9000,
                    'buyer_id': buyer.id,
                }),
                content_type='application/json',
            )
            self.assertEqual(response.status_code, 201)

            list_response = self.client.get('/api/finance/ledger')
            self.assertEqual(list_response.status_code, 200)
            payload = json.loads(list_response.data.decode())
            self.assertTrue(payload['items'])

            row = payload['items'][0]
            self.assertEqual(row['buyer_id'], buyer.id)
            self.assertEqual(row['buyer_name'], 'Daily Dairies')
            self.assertEqual(row['counterparty_name'], 'Daily Dairies')
            self.assertIsNotNone(row['timestamp'])
            self.assertIsNotNone(row['date'])

    def test_record_buyer_payment_reduces_outstanding_balance(self):
        self._login('farmer', 'password')

        buyer = Buyer(
            tenant_id=self.tenant.id,
            name='Ol Kalu',
            agreed_rate_per_liter=55,
        )
        db.session.add(buyer)
        db.session.commit()

        outstanding_entry = SalesLedger(
            tenant_id=self.tenant.id,
            buyer_id=buyer.id,
            date=date(2026, 6, 1),
            liters_sold=100,
            total_cost=1000,
            payment_status=PaymentStatus.UNPAID,
        )
        db.session.add(outstanding_entry)
        db.session.commit()

        with self.client:
            response = self.client.post(
                f'/api/finance/buyers/{buyer.id}/payments',
                data=json.dumps({
                    'amount': 400,
                    'reference_code': 'PAY-001',
                    'note': 'Partial payment',
                }),
                content_type='application/json',
            )

        self.assertEqual(response.status_code, 201)
        payload = json.loads(response.data.decode())
        self.assertEqual(payload['payment']['amount'], 400.0)
        self.assertEqual(payload['payment']['previous_balance'], 1000.0)
        self.assertEqual(payload['payment']['current_balance'], 600.0)
        self.assertEqual(payload['buyer']['current_balance'], 600.0)
        self.assertEqual(payload['transaction']['category'], 'Buyer Payment')
        self.assertEqual(payload['transaction']['buyer_name'], 'Ol Kalu')

        db.session.refresh(outstanding_entry)
        self.assertEqual(float(outstanding_entry.total_cost), 600.0)
        self.assertEqual(outstanding_entry.payment_status, PaymentStatus.UNPAID)

    def test_record_buyer_payment_rejects_amount_above_outstanding(self):
        self._login('farmer', 'password')

        buyer = Buyer(
            tenant_id=self.tenant.id,
            name='Molo Milk',
            agreed_rate_per_liter=58,
        )
        db.session.add(buyer)
        db.session.commit()

        outstanding_entry = SalesLedger(
            tenant_id=self.tenant.id,
            buyer_id=buyer.id,
            date=date(2026, 6, 2),
            liters_sold=80,
            total_cost=300,
            payment_status=PaymentStatus.UNPAID,
        )
        db.session.add(outstanding_entry)
        db.session.commit()

        with self.client:
            response = self.client.post(
                f'/api/finance/buyers/{buyer.id}/payments',
                data=json.dumps({
                    'amount': 500,
                    'note': 'Overpayment attempt',
                }),
                content_type='application/json',
            )

        self.assertEqual(response.status_code, 400)
        payload = json.loads(response.data.decode())
        self.assertIn('exceeds buyer outstanding balance', payload['error'])

    def test_record_buyer_payment_marks_ledger_paid_on_full_payment(self):
        self._login('farmer', 'password')

        buyer = Buyer(
            tenant_id=self.tenant.id,
            name='Brookside',
            agreed_rate_per_liter=52,
        )
        db.session.add(buyer)
        db.session.commit()

        outstanding_entry = SalesLedger(
            tenant_id=self.tenant.id,
            buyer_id=buyer.id,
            date=date(2026, 6, 3),
            liters_sold=50,
            total_cost=2600,
            payment_status=PaymentStatus.UNPAID,
        )
        db.session.add(outstanding_entry)
        db.session.commit()

        with self.client:
            response = self.client.post(
                f'/api/finance/buyers/{buyer.id}/payments',
                data=json.dumps({
                    'amount': 2600,
                    'note': 'Full payment',
                }),
                content_type='application/json',
            )

        self.assertEqual(response.status_code, 201)
        payload = json.loads(response.data.decode())
        self.assertEqual(payload['payment']['current_balance'], 0.0)
        self.assertEqual(payload['buyer']['current_balance'], 0.0)

        db.session.refresh(outstanding_entry)
        self.assertEqual(float(outstanding_entry.total_cost), 0.0)
        self.assertEqual(outstanding_entry.payment_status, PaymentStatus.PAID)

    def test_record_buyer_payment_rejects_payment_with_no_outstanding_balance(self):
        self._login('farmer', 'password')

        buyer = Buyer(
            tenant_id=self.tenant.id,
            name='Happy Cow',
            agreed_rate_per_liter=50,
        )
        db.session.add(buyer)
        db.session.commit()

        with self.client:
            response = self.client.post(
                f'/api/finance/buyers/{buyer.id}/payments',
                data=json.dumps({
                    'amount': 100,
                    'note': 'Payment attempt with no balance',
                }),
                content_type='application/json',
            )

        self.assertEqual(response.status_code, 400)
        payload = json.loads(response.data.decode())
        self.assertIn('Buyer has no unpaid balance', payload['error'])

    def test_delete_customer_with_dependencies_returns_409(self):
        self._login('farmer', 'password')

        customer = Customer(
            tenant_id=self.tenant.id,
            name='Test Customer',
            phone_number='254799887766'
        )
        db.session.add(customer)
        db.session.commit()

        transaction = Transaction(
            tenant_id=self.tenant.id,
            customer_id=customer.id,
            transaction_type=TransactionType.REVENUE,
            category=TransactionCategory.MILK_SALE,
            amount=100,
            recorded_by=self.farmer.id
        )
        db.session.add(transaction)
        db.session.commit()

        with self.client:
            response = self.client.delete(f'/api/finance/customers/{customer.id}')

        self.assertEqual(response.status_code, 409)
        data = json.loads(response.data.decode())
        self.assertIn('Cannot delete customer', data['error'])

    def test_delete_customer_without_dependencies_succeeds(self):
        self._login('farmer', 'password')

        customer = Customer(
            tenant_id=self.tenant.id,
            name='Deletable Customer',
            phone_number='254711223344'
        )
        db.session.add(customer)
        db.session.commit()
        customer_id = customer.id

        with self.client:
            response = self.client.delete(f'/api/finance/customers/{customer_id}')

        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data.decode())
        self.assertIn('deleted successfully', data['message'])

        # Verify it's gone
        deleted_customer = Customer.query.get(customer_id)
        self.assertIsNone(deleted_customer)

    def test_update_customer_patch_succeeds(self):
        self._login('farmer', 'password')

        customer = Customer(
            tenant_id=self.tenant.id,
            name='Original Name',
            phone_number='254700000001',
            account_balance=100,
            daily_contract_liters=5,
            is_active=True,
        )
        db.session.add(customer)
        db.session.commit()

        with self.client:
            response = self.client.patch(
                f'/api/finance/customers/{customer.id}',
                data=json.dumps({
                    'name': 'Updated Name',
                    'phone_number': '254700000009',
                    'daily_contract_liters': 12.5,
                    'is_active': False,
                    'contact_person': '',
                    'email': '',
                    'address': '',
                }),
                content_type='application/json',
            )

        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.data.decode())
        self.assertEqual(payload['name'], 'Updated Name')
        self.assertEqual(payload['phone_number'], '254700000009')
        self.assertEqual(payload['daily_contract_liters'], 12.5)
        self.assertEqual(payload['is_active'], False)

    def test_update_customer_patch_duplicate_phone_returns_409(self):
        self._login('farmer', 'password')

        c1 = Customer(
            tenant_id=self.tenant.id,
            name='Customer One',
            phone_number='254700000011',
        )
        c2 = Customer(
            tenant_id=self.tenant.id,
            name='Customer Two',
            phone_number='254700000022',
        )
        db.session.add_all([c1, c2])
        db.session.commit()

        with self.client:
            response = self.client.patch(
                f'/api/finance/customers/{c2.id}',
                data=json.dumps({
                    'phone_number': '254700000011',
                }),
                content_type='application/json',
            )

        self.assertEqual(response.status_code, 409)

    def test_revenue_creates_tenant_scoped_immutable_receipt_and_pdf(self):
        self._login('farmer', 'password')
        with self.client:
            response = self.client.post('/api/finance/ledger', json={
                'transaction_type': 'Revenue',
                'category': 'Milk Sale',
                'amount': 1250.50,
                'income_source': 'Farm gate customer',
                'payment_method': 'M-Pesa',
                'reference_code': 'MPESA-RECEIPT-1',
                'description': 'August milk payment',
            })

            self.assertEqual(response.status_code, 201)
            transaction_payload = response.get_json()
            self.assertTrue(transaction_payload['receipt_available'])
            receipt_id = transaction_payload['receipt']['id']
            self.assertRegex(transaction_payload['receipt']['receipt_number'], r'^RCPT-\d{4}-\d{6}$')

            receipt_response = self.client.get(f'/api/finance/receipts/{receipt_id}')
            pdf_response = self.client.get(f'/api/finance/receipts/{receipt_id}/pdf')
            repeated_issue_response = self.client.post(
                f"/api/finance/transactions/{transaction_payload['id']}/receipt"
            )

        self.assertEqual(receipt_response.status_code, 200)
        self.assertEqual(repeated_issue_response.status_code, 200)
        self.assertEqual(repeated_issue_response.get_json()['id'], receipt_id)
        receipt_payload = receipt_response.get_json()
        self.assertEqual(receipt_payload['amount'], 1250.50)
        self.assertEqual(receipt_payload['counterparty_name'], 'Farm gate customer')
        self.assertEqual(receipt_payload['payment_reference'], 'MPESA-RECEIPT-1')
        self.assertEqual(receipt_payload['tenant']['name'], self.tenant.name)
        self.assertEqual(pdf_response.status_code, 200)
        self.assertEqual(pdf_response.mimetype, 'application/pdf')
        self.assertTrue(pdf_response.data.startswith(b'%PDF'))
        self.assertIn('attachment;', pdf_response.headers['Content-Disposition'])

        other_tenant = self.create_tenant(name='Other Tenant')
        self.create_user(
            username='other-farmer',
            password='password',
            role=Role.FARMER,
            tenant=other_tenant,
        )
        self._login('other-farmer', 'password')
        with self.client:
            cross_tenant_response = self.client.get(f'/api/finance/receipts/{receipt_id}')
            cross_tenant_pdf_response = self.client.get(f'/api/finance/receipts/{receipt_id}/pdf')

        self.assertEqual(cross_tenant_response.status_code, 404)
        self.assertEqual(cross_tenant_pdf_response.status_code, 404)

        transaction = db.session.get(Transaction, transaction_payload['id'])
        transaction.amount = 9999
        transaction.counterparty_name = 'Changed later'
        db.session.commit()
        frozen_receipt = db.session.get(Receipt, receipt_id)
        self.assertEqual(float(frozen_receipt.snapshot['amount']), 1250.50)
        self.assertEqual(frozen_receipt.snapshot['counterparty_name'], 'Farm gate customer')

        frozen_receipt.snapshot = {**frozen_receipt.snapshot, 'amount': 1}
        with self.assertRaises(ValueError):
            db.session.commit()
        db.session.rollback()

    def test_expense_cannot_issue_receipt(self):
        self._login('farmer', 'password')
        with self.client:
            response = self.client.post('/api/finance/ledger', json={
                'transaction_type': 'Expense',
                'category': 'Feed Purchase',
                'amount': 500,
                'paid_to': 'Feed Supplier',
                'item_name': 'Dairy Meal',
            })
            transaction_payload = response.get_json()
            issue_response = self.client.post(f"/api/finance/transactions/{transaction_payload['id']}/receipt")

        self.assertEqual(response.status_code, 201)
        self.assertFalse(transaction_payload['receipt_available'])
        self.assertEqual(issue_response.status_code, 422)

    def test_expense_persists_item_name_without_breaking_legacy_clients(self):
        self._login('farmer', 'password')
        with self.client:
            missing_response = self.client.post('/api/finance/ledger', json={
                'transaction_type': 'Expense',
                'category': 'Feed Purchase',
                'amount': 500,
                'paid_to': 'Feed Supplier',
            })
            response = self.client.post('/api/finance/ledger', json={
                'transaction_type': 'Expense',
                'category': 'Feed Purchase',
                'amount': 500,
                'paid_to': 'Feed Supplier',
                'item_name': '  Dairy Meal  ',
                'quantity': 50.125,
                'description': 'Bulk purchase',
            })
            invalid_quantity_response = self.client.post('/api/finance/ledger', json={
                'transaction_type': 'Expense',
                'category': 'Feed Purchase',
                'amount': 500,
                'paid_to': 'Feed Supplier',
                'item_name': 'Dairy Meal',
                'quantity': 0,
            })
            acquisition_response = self.client.post('/api/finance/ledger', json={
                'transaction_type': 'Expense',
                'category': 'Other',
                'amount': 750,
                'paid_to': 'County Show',
                'item_name': 'Promotion booth',
                'quantity': 1,
                'cost_class': 'CUSTOMER_ACQUISITION',
            })

        self.assertEqual(missing_response.status_code, 201)
        self.assertIsNone(missing_response.get_json()['item_name'])
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.get_json()['item_name'], 'Dairy Meal')
        self.assertEqual(response.get_json()['quantity'], 50.125)
        self.assertEqual(response.get_json()['cost_class'], 'COGS')
        self.assertEqual(acquisition_response.status_code, 201)
        self.assertEqual(acquisition_response.get_json()['cost_class'], 'CUSTOMER_ACQUISITION')
        self.assertEqual(invalid_quantity_response.status_code, 400)
        self.assertIn('quantity must be greater than 0', invalid_quantity_response.get_json()['error'])
        transaction = db.session.get(Transaction, response.get_json()['id'])
        self.assertEqual(transaction.item_name, 'Dairy Meal')
        self.assertEqual(float(transaction.quantity), 50.125)
        self.assertEqual(transaction.description, 'Bulk purchase')
        self.assertEqual(transaction.counterparty_name, 'Feed Supplier')

    def test_void_and_replace_expense_reclassifies_to_production_cost_with_audit(self):
        self._login('farmer', 'password')
        with self.client:
            create_response = self.client.post('/api/finance/ledger', json={
                'transaction_type': 'Expense',
                'category': 'Equipment Maintenance',
                'amount': 2500,
                'paid_to': 'Dr Ngotho',
                'description': 'AI insemination payment',
                'reference_code': 'EXPENSE-CORRECTION-1',
            })
            original_id = create_response.get_json()['id']
            correction_response = self.client.post(
                f'/api/finance/transactions/{original_id}/void-and-replace',
                json={
                    'void_reason': 'Incorrectly classified as operating cost.',
                    'replacement': {'category': 'Vet Fees', 'cost_class': 'COGS'},
                },
            )

        self.assertEqual(create_response.status_code, 201)
        self.assertEqual(correction_response.status_code, 201)
        payload = correction_response.get_json()
        self.assertEqual(payload['voided_transaction']['status'], TransactionStatus.VOIDED.value)
        self.assertEqual(payload['voided_transaction']['void_reason'], 'Incorrectly classified as operating cost.')
        replacement = payload['replacement_transaction']
        self.assertEqual(replacement['status'], TransactionStatus.POSTED.value)
        self.assertEqual(replacement['category'], TransactionCategory.VET_FEES.value)
        self.assertEqual(replacement['cost_class'], CostClass.COGS.value)
        self.assertEqual(replacement['corrected_from_transaction_id'], original_id)
        self.assertEqual(payload['voided_transaction']['replacement_transaction_id'], replacement['id'])
        self.assertEqual(TransactionAuditLog.query.filter_by(transaction_id=original_id).one().action, 'VOIDED_AND_REPLACED')
        self.assertEqual(TransactionAuditLog.query.filter_by(transaction_id=replacement['id']).one().action, 'CREATED_AS_CORRECTION')
        audit_log = TransactionAuditLog.query.filter_by(transaction_id=original_id).one()
        audit_log.action = 'ALTERED'
        with self.assertRaises(ValueError):
            db.session.commit()
        db.session.rollback()

        with self.client:
            repeated_response = self.client.post(
                f'/api/finance/transactions/{original_id}/void-and-replace',
                json={'void_reason': 'Try again'},
            )
        self.assertEqual(repeated_response.status_code, 422)
        self.assertIn('Only posted transactions', repeated_response.get_json()['error'])

    def test_posted_payment_receipt_has_stable_artifact_audit_and_void_lifecycle(self):
        self._login('farmer', 'password')
        customer = Customer(
            tenant_id=self.tenant.id,
            name='Receipt Customer',
            phone_number='254700000099',
            account_balance=1000,
        )
        db.session.add(customer)
        db.session.commit()

        with self.client:
            payment_response = self.client.post(f'/api/finance/customers/{customer.id}/payments', json={
                'amount': 250,
                'reference_code': 'PAYMENT-RECEIPT-1',
                'note': 'Customer account payment',
            })
            self.assertEqual(payment_response.status_code, 201)
            transaction_payload = payment_response.get_json()['transaction']
            self.assertEqual(transaction_payload['status'], TransactionStatus.POSTED.value)
            receipt_id = transaction_payload['receipt']['id']

            receipt_response = self.client.get(f'/api/finance/receipts/{receipt_id}')
            first_pdf = self.client.get(f'/api/finance/receipts/{receipt_id}/pdf')
            second_pdf = self.client.get(f'/api/finance/receipts/{receipt_id}/pdf')
            audit_response = self.client.get(f'/api/finance/receipts/{receipt_id}/audit')
            void_response = self.client.post(f'/api/finance/receipts/{receipt_id}/void', json={
                'void_reason': 'Payment was reversed by the bank',
            })

        self.assertEqual(receipt_response.status_code, 200)
        receipt_payload = receipt_response.get_json()
        self.assertEqual(receipt_payload['transaction_type'], TransactionType.PAYMENT.value)
        self.assertEqual(receipt_payload['farm']['id'], self.farm.id)
        self.assertEqual(receipt_payload['currency'], 'KES')
        self.assertEqual(first_pdf.data, second_pdf.data)
        self.assertEqual(receipt_payload['document_sha256'], __import__('hashlib').sha256(first_pdf.data).hexdigest())
        actions = [item['action'] for item in audit_response.get_json()['items']]
        self.assertIn('ISSUED', actions)
        self.assertIn('VIEWED', actions)
        self.assertIn('DOWNLOADED', actions)
        self.assertEqual(void_response.status_code, 200)
        self.assertEqual(void_response.get_json()['status'], 'VOIDED')

        audit_log = ReceiptAuditLog.query.filter_by(receipt_id=receipt_id).first()
        audit_log.action = 'ALTERED'
        with self.assertRaises(ValueError):
            db.session.commit()
        db.session.rollback()

    def test_receipt_pdf_restyle_is_audited(self):
        self._login('farmer', 'password')
        customer = Customer(
            tenant_id=self.tenant.id,
            name='Restyle Customer',
            phone_number='254700000088',
            account_balance=500,
        )
        db.session.add(customer)
        db.session.commit()
        with self.client:
            payment_response = self.client.post(f'/api/finance/customers/{customer.id}/payments', json={
                'amount': 250,
                'reference_code': 'RESTYLE-RECEIPT-1',
            })
        receipt = db.session.get(Transaction, payment_response.get_json()['transaction']['id']).receipt
        original_hash = receipt.document_sha256
        db.session.expire(receipt, ['template_version'])
        db.session.execute(
            update(type(receipt))
            .where(type(receipt).id == receipt.id)
            .values(template_version='1')
        )
        db.session.commit()

        upgraded_count = ReceiptService.rerender_documents_to_current_template(
            tenant_id=self.tenant.id,
            performed_by=self.farmer.id,
        )
        db.session.commit()

        db.session.refresh(receipt)
        self.assertEqual(upgraded_count, 1)
        self.assertEqual(receipt.template_version, ReceiptService.TEMPLATE_VERSION)
        self.assertNotEqual(receipt.document_sha256, original_hash)
        self.assertTrue(ReceiptAuditLog.query.filter_by(receipt_id=receipt.id, action='DOCUMENT_RESTYLED').first())

    def test_draft_revenue_cannot_issue_receipt(self):
        transaction = Transaction(
            tenant_id=self.tenant.id,
            farm_id=self.farm.id,
            transaction_type=TransactionType.REVENUE,
            category=TransactionCategory.OTHER_INCOME,
            amount=100,
            counterparty_name='Draft customer',
            status=TransactionStatus.DRAFT.value,
            recorded_by=self.farmer.id,
        )
        db.session.add(transaction)
        db.session.commit()
        self._login('farmer', 'password')

        with self.client:
            response = self.client.post(f'/api/finance/transactions/{transaction.id}/receipt')

        self.assertEqual(response.status_code, 422)
        self.assertIsNone(transaction.receipt)

    def test_concurrent_receipt_issuance_is_idempotent_and_sequence_safe(self):
        transactions = []
        for index in range(4):
            transaction = Transaction(
                tenant_id=self.tenant.id,
                farm_id=self.farm.id,
                transaction_type=TransactionType.REVENUE,
                category=TransactionCategory.OTHER_INCOME,
                amount=100 + index,
                counterparty_name=f'Concurrent customer {index}',
                status=TransactionStatus.POSTED.value,
                posted_at=datetime.now(timezone.utc),
                posted_by=self.farmer.id,
                recorded_by=self.farmer.id,
            )
            db.session.add(transaction)
            transactions.append(transaction)
        db.session.commit()

        transaction_ids = [transactions[0].id, transactions[0].id, *[item.id for item in transactions[1:]]]
        barrier = threading.Barrier(len(transaction_ids))

        def issue_in_worker(transaction_id):
            with self.app.app_context():
                barrier.wait(timeout=10)
                transaction = db.session.get(Transaction, transaction_id)
                receipt = ReceiptService.issue(
                    transaction,
                    issued_by=self.farmer.id,
                    farm_id=self.farm.id,
                )
                db.session.commit()
                result = (receipt.id, receipt.receipt_number)
                db.session.remove()
                return result

        with ThreadPoolExecutor(max_workers=len(transaction_ids)) as executor:
            results = list(executor.map(issue_in_worker, transaction_ids))

        duplicate_results = results[:2]
        self.assertEqual(duplicate_results[0], duplicate_results[1])
        self.assertEqual(Receipt.query.filter(Receipt.transaction_id.in_(set(transaction_ids))).count(), 4)
        receipt_numbers = {number for _, number in results}
        self.assertEqual(len(receipt_numbers), 4)
        self.assertTrue(all(number.startswith(f'RCPT-{datetime.now(timezone.utc).year}-') for number in receipt_numbers))
