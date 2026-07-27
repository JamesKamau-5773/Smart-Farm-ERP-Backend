"""
Tests for BuyerService - business logic layer tests.
"""

from datetime import date
from decimal import Decimal
from app import db
from app.models.finance import Buyer, SalesLedger, PaymentStatus, Transaction, PaymentAllocation
from app.services.buyer_service import BuyerService, DuplicateBuyerError
from tests.base import BaseTestCase


class TestBuyerService(BaseTestCase):
    """Test suite for the BuyerService."""

    def test_create_buyer_success(self):
        """Test successful creation of a buyer."""
        buyer = BuyerService.create_buyer(
            tenant_id=self.tenant.id,
            name="Test Buyer",
            agreed_rate_per_liter=50.0
        )
        self.assertIsNotNone(buyer.id)
        self.assertEqual(buyer.name, "Test Buyer")
        self.assertEqual(float(buyer.agreed_rate_per_liter), 50.0)

    def test_create_buyer_with_opening_balance(self):
        """Test creating a buyer with an opening balance creates a ledger entry."""
        buyer = BuyerService.create_buyer(
            tenant_id=self.tenant.id,
            name="Buyer With Debt",
            agreed_rate_per_liter=55.0,
            opening_balance=1000.0
        )
        self.assertIsNotNone(buyer.id)

        # Check that a SalesLedger entry was created for the opening balance
        ledger_entry = SalesLedger.query.filter_by(buyer_id=buyer.id).first()
        self.assertIsNotNone(ledger_entry)
        self.assertEqual(ledger_entry.shift, "Opening")
        self.assertEqual(float(ledger_entry.total_cost), 1000.0)
        self.assertEqual(ledger_entry.payment_status, PaymentStatus.UNPAID)

        # Check the balance
        balance = BuyerService.get_buyer_balance(buyer.id, self.tenant.id)
        self.assertEqual(balance, 1000.0)

    def test_create_duplicate_buyer_fails(self):
        """Test that creating a buyer with a duplicate name fails."""
        BuyerService.create_buyer(
            tenant_id=self.tenant.id,
            name="Unique Buyer",
            agreed_rate_per_liter=50.0
        )
        with self.assertRaises(DuplicateBuyerError):
            BuyerService.create_buyer(
                tenant_id=self.tenant.id,
                name="Unique Buyer",
                agreed_rate_per_liter=50.0
            )

    def test_allocate_payment_full_payment(self):
        """Test a payment that fully pays one invoice."""
        # Setup: Create a buyer with an unpaid invoice
        buyer = BuyerService.create_buyer(
            tenant_id=self.tenant.id, name="Payer", agreed_rate_per_liter=50
        )
        invoice = SalesLedger(
            tenant_id=self.tenant.id,
            buyer_id=buyer.id,
            date=date.today(),
            liters_sold=20,
            total_cost=Decimal("1000.00"),
            payment_status=PaymentStatus.UNPAID
        )
        db.session.add(invoice)
        db.session.commit()

        self.assertEqual(BuyerService.get_buyer_balance(buyer.id, self.tenant.id), 1000.0)

        # Action: Allocate a full payment
        result = BuyerService.allocate_payment(
            buyer_id=buyer.id,
            tenant_id=self.tenant.id,
            amount=1000.0,
            recorded_by=self.user.id
        )

        # Assertions
        self.assertEqual(result['applied_amount'], 1000.0)
        self.assertEqual(result['unallocated_credit'], 0.0)
        self.assertEqual(result['current_balance'], 0.0)
        
        db.session.refresh(invoice)
        self.assertEqual(invoice.payment_status, PaymentStatus.PAID)
        self.assertEqual(float(invoice.amount_paid), 1000.0)
        
        tx = Transaction.query.filter_by(buyer_id=buyer.id).first()
        self.assertIsNotNone(tx)
        self.assertEqual(float(tx.amount), 1000.0)
        
        allocation = PaymentAllocation.query.filter_by(transaction_id=tx.id).first()
        self.assertIsNotNone(allocation)
        self.assertEqual(allocation.sales_ledger_id, invoice.id)
        self.assertEqual(float(allocation.amount_applied), 1000.0)

    def test_allocate_payment_partial_payment(self):
        """Test a partial payment on a single invoice."""
        buyer = BuyerService.create_buyer(
            tenant_id=self.tenant.id, name="Partial Payer", agreed_rate_per_liter=50
        )
        invoice = SalesLedger(
            tenant_id=self.tenant.id, buyer_id=buyer.id, date=date.today(),
            liters_sold=20, total_cost=Decimal("1000.00"), payment_status=PaymentStatus.UNPAID
        )
        db.session.add(invoice)
        db.session.commit()

        BuyerService.allocate_payment(
            buyer_id=buyer.id, tenant_id=self.tenant.id, amount=400.0, recorded_by=self.user.id
        )

        self.assertEqual(BuyerService.get_buyer_balance(buyer.id, self.tenant.id), 600.0)
        db.session.refresh(invoice)
        self.assertEqual(invoice.payment_status, PaymentStatus.PARTIALLY_PAID)
        self.assertEqual(float(invoice.amount_paid), 400.0)

    def test_allocate_payment_waterfall_across_invoices(self):
        """Test a payment that covers one invoice fully and another partially."""
        buyer = BuyerService.create_buyer(
            tenant_id=self.tenant.id, name="Waterfall Payer", agreed_rate_per_liter=50
        )
        invoice1 = SalesLedger(
            tenant_id=self.tenant.id, buyer_id=buyer.id, date=date(2023, 1, 1),
            liters_sold=10, total_cost=Decimal("500.00"), payment_status=PaymentStatus.UNPAID
        )
        invoice2 = SalesLedger(
            tenant_id=self.tenant.id, buyer_id=buyer.id, date=date(2023, 1, 2),
            liters_sold=10, total_cost=Decimal("500.00"), payment_status=PaymentStatus.UNPAID
        )
        db.session.add_all([invoice1, invoice2])
        db.session.commit()

        self.assertEqual(BuyerService.get_buyer_balance(buyer.id, self.tenant.id), 1000.0)

        BuyerService.allocate_payment(
            buyer_id=buyer.id, tenant_id=self.tenant.id, amount=700.0, recorded_by=self.user.id
        )

        self.assertEqual(BuyerService.get_buyer_balance(buyer.id, self.tenant.id), 300.0)
        db.session.refresh(invoice1)
        db.session.refresh(invoice2)
        self.assertEqual(invoice1.payment_status, PaymentStatus.PAID)
        self.assertEqual(float(invoice1.amount_paid), 500.0)
        self.assertEqual(invoice2.payment_status, PaymentStatus.PARTIALLY_PAID)
        self.assertEqual(float(invoice2.amount_paid), 200.0)