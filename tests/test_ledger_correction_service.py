from datetime import datetime, timezone
from decimal import Decimal

from app import db
from app.models.finance import Customer, Transaction, TransactionCategory, TransactionStatus, TransactionType
from app.models.user import Role
from app.services.ledger_correction_service import LedgerCorrectionService
from app.services.receipt_service import ReceiptService
from tests.base import BaseTestCase


class LedgerCorrectionServiceTestCase(BaseTestCase):
    def test_reclassifies_revenue_as_payment_and_preserves_receipt_audit(self):
        user = self.create_user(username='farmer', password='password', role=Role.FARMER)
        customer = Customer(tenant_id=self.tenant.id, name='Baba Wangari', phone_number='254700000111', account_balance=Decimal('18250.00'))
        db.session.add(customer)
        db.session.flush()
        original = Transaction(
            tenant_id=self.tenant.id,
            farm_id=self.farm.id,
            customer_id=customer.id,
            transaction_type=TransactionType.REVENUE,
            category=TransactionCategory.MILK_SALE,
            amount=Decimal('18000.00'),
            description='milk payment',
            payment_method='Cash',
            timestamp=datetime(2026, 8, 30, tzinfo=timezone.utc),
            recorded_by=user.id,
            status=TransactionStatus.POSTED.value,
        )
        db.session.add(original)
        db.session.flush()
        original_receipt = ReceiptService.issue(original, issued_by=user.id, farm_id=self.farm.id)
        db.session.commit()

        replacement = LedgerCorrectionService.reclassify_customer_revenue_as_payment(
            tenant_id=self.tenant.id,
            transaction_id=original.id,
            payment_reference='LEGACY-CUSTOMER-PAYMENT-1',
            corrected_by=user.id,
        )

        db.session.refresh(customer)
        db.session.refresh(original)
        db.session.refresh(original_receipt)
        self.assertEqual(original.status, TransactionStatus.VOIDED.value)
        self.assertEqual(original_receipt.status, 'VOIDED')
        self.assertEqual(replacement.transaction_type, TransactionType.PAYMENT)
        self.assertEqual(replacement.category, TransactionCategory.PAYMENT)
        self.assertEqual(replacement.customer_id, customer.id)
        self.assertEqual(replacement.payment_method, 'Cash')
        self.assertEqual(customer.account_balance, Decimal('250.00'))
        self.assertIsNotNone(replacement.receipt)
