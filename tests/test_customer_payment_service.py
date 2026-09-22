import json
from datetime import date
from decimal import Decimal

from app import db
from app.models.finance import Buyer, Customer, Delivery, PaymentStatus, SalesLedger, Transaction, TransactionCategory, TransactionType
from app.models.user import Role
from app.services.buyer_service import BuyerService
from app.services.payment_service import PaymentService
from tests.base import BaseTestCase


class CustomerPaymentServiceTestCase(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.customer = Customer(
            tenant_id=self.tenant.id,
            name='Month End Customer',
            phone_number='254700000001',
            agreed_rate_per_liter=Decimal('60.00'),
            account_balance=Decimal('600.00'),
        )
        db.session.add(self.customer)
        db.session.commit()

    def test_customer_payment_endpoint_records_payment(self):
        self.create_user(username='farmer', password='password', role=Role.FARMER)
        self.client.post(
            '/api/auth/login',
            data=json.dumps({'username': 'farmer', 'password': 'password'}),
            content_type='application/json',
        )

        response = self.client.post(
            f'/api/customers/{self.customer.id}/payments',
            data=json.dumps({
                'amount': 200,
                'reference_code': 'CASH-API-001',
                'payment_method': 'Cash',
                'date': '2026-08-30',
            }),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 201)
        payload = response.get_json()
        self.assertEqual(payload['transaction']['transaction_type'], 'Payment')
        self.assertEqual(payload['transaction']['category'], 'Payment')
        self.assertEqual(payload['transaction']['payment_method'], 'Cash')
        self.assertEqual(payload['transaction']['date'][:10], date(2026, 8, 30).isoformat())
        self.assertEqual(payload['customer']['account_balance'], 400.0)

    def test_payment_is_distinct_from_delivery_revenue(self):
        delivery = Delivery(
            tenant_id=self.tenant.id,
            customer_id=self.customer.id,
            date=db.func.current_date(),
            liters_delivered=Decimal('10.00'),
            personal_consumption_liters=Decimal('0.00'),
            billable_liters=Decimal('10.00'),
            price_per_liter=Decimal('60.00'),
            total_price=Decimal('600.00'),
        )
        db.session.add(delivery)
        db.session.commit()

        customer, payment = PaymentService.record_customer_payment(
            tenant_id=self.tenant.id,
            customer_id=self.customer.id,
            amount=200,
            reference_code='CASH-001',
        )

        self.assertEqual(payment.transaction_type, TransactionType.PAYMENT)
        self.assertEqual(payment.category, TransactionCategory.PAYMENT)
        self.assertEqual(customer.account_balance, Decimal('400.00'))
        self.assertEqual(
            db.session.query(db.func.sum(Delivery.total_price)).filter_by(
                tenant_id=self.tenant.id,
                customer_id=self.customer.id,
            ).scalar(),
            Decimal('600.00'),
        )

    def test_duplicate_receipt_reference_cannot_reduce_balance_twice(self):
        PaymentService.record_customer_payment(
            tenant_id=self.tenant.id,
            customer_id=self.customer.id,
            amount=200,
            reference_code='MPESA-001',
        )

        with self.assertRaisesRegex(ValueError, 'already been recorded'):
            PaymentService.record_customer_payment(
                tenant_id=self.tenant.id,
                customer_id=self.customer.id,
                amount=200,
                reference_code='MPESA-001',
            )

        db.session.refresh(self.customer)
        self.assertEqual(self.customer.account_balance, Decimal('400.00'))
        self.assertEqual(
            Transaction.query.filter_by(
                tenant_id=self.tenant.id,
                reference_code='MPESA-001',
            ).count(),
            1,
        )

    def test_buyer_allocation_uses_canonical_payment_transaction(self):
        buyer = Buyer(
            tenant_id=self.tenant.id,
            name='Dairy Buyer',
            agreed_rate_per_liter=Decimal('55.00'),
        )
        db.session.add(buyer)
        db.session.flush()
        db.session.add(SalesLedger(
            tenant_id=self.tenant.id,
            buyer_id=buyer.id,
            date=db.func.current_date(),
            liters_sold=Decimal('10.00'),
            total_cost=Decimal('550.00'),
            payment_status=PaymentStatus.UNPAID,
        ))
        db.session.commit()

        result = BuyerService.allocate_payment(
            buyer_id=buyer.id,
            tenant_id=self.tenant.id,
            amount=200,
            reference_code='BUYER-PAY-001',
        )

        self.assertEqual(result['transaction'].transaction_type, TransactionType.PAYMENT)
        self.assertEqual(result['transaction'].category, TransactionCategory.BUYER_PAYMENT)
        self.assertEqual(result['applied_amount'], 200.0)
