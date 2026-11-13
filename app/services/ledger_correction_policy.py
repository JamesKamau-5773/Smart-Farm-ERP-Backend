"""Whether a posted ledger entry may be corrected, and what the corrected values are. No persistence."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Optional

from app.models.finance import CostClass, Transaction, TransactionCategory, TransactionStatus, TransactionType
from app.services import ledger_category_policy


@dataclass(frozen=True)
class Correction:
    reason: str
    category: TransactionCategory
    cost_class: Optional[CostClass]
    amount: Decimal


class LedgerCorrectionPolicy:
    @staticmethod
    def decide(original: Optional[Transaction], *, void_reason, category=None, cost_class=None, amount=None) -> Correction:
        """Raises ValueError with a user-facing message when the correction isn't allowed."""
        reason = str(void_reason or '').strip()
        if not reason:
            raise ValueError('void_reason is required.')
        LedgerCorrectionPolicy._check_correctable(original)
        replacement_category = LedgerCorrectionPolicy._category(original, category)
        replacement_amount = LedgerCorrectionPolicy._amount(original, amount)
        return Correction(
            reason=reason[:255],
            category=replacement_category,
            cost_class=LedgerCorrectionPolicy._cost_class(original, replacement_category, cost_class),
            amount=replacement_amount,
        )

    @staticmethod
    def _check_correctable(original: Optional[Transaction]) -> None:
        if original is None:
            raise ValueError('Transaction not found.')
        if original.transaction_type not in (TransactionType.EXPENSE, TransactionType.REVENUE):
            raise ValueError('Only income and expense entries can be corrected here.')
        if original.status != TransactionStatus.POSTED.value:
            raise ValueError('Only posted transactions can be voided and replaced.')
        if original.correction_replacement is not None:
            raise ValueError('This transaction has already been corrected.')
        if original.transaction_type == TransactionType.REVENUE and (original.customer_id is not None or original.buyer_id is not None):
            raise ValueError('Income linked to a customer or buyer account is corrected through that account, not here.')

    @staticmethod
    def _category(original: Transaction, value) -> TransactionCategory:
        try:
            category = TransactionCategory(value) if value else original.category
        except ValueError as exc:
            raise ValueError('Invalid replacement category.') from exc
        # The original category is always allowed, so an entry posted by a workflow (e.g. AI Service) can keep it.
        allowed = set(ledger_category_policy.categories_for(original.transaction_type)) | {original.category}
        if category not in allowed:
            kind = 'an expense' if original.transaction_type == TransactionType.EXPENSE else 'an income'
            raise ValueError(f'Replacement category must be valid for {kind} entry.')
        return category

    @staticmethod
    def _cost_class(original: Transaction, category: TransactionCategory, value) -> Optional[CostClass]:
        if original.transaction_type != TransactionType.EXPENSE:
            if value:
                raise ValueError('cost_class is only valid for expense entries.')
            return None
        try:
            return CostClass(value) if value else ledger_category_policy.default_cost_class(category)
        except ValueError as exc:
            raise ValueError('Invalid replacement cost_class.') from exc

    @staticmethod
    def _amount(original: Transaction, value) -> Decimal:
        if value in (None, ''):
            return Decimal(original.amount)
        try:
            amount = Decimal(str(value)).quantize(Decimal('0.01'))
        except (InvalidOperation, TypeError, ValueError):
            raise ValueError('amount must be a number.')
        if not amount.is_finite() or amount <= 0:
            raise ValueError('amount must be greater than 0.')
        if amount != original.amount:
            lock_reason = LedgerCorrectionPolicy.amount_lock_reason(original)
            if lock_reason:
                raise ValueError(lock_reason)
        return amount

    @staticmethod
    def amount_lock_reason(original: Transaction) -> Optional[str]:
        """Why a correction must keep this entry's amount, or None when the amount may change."""
        # Entries that mirror another record keep their amount; it is corrected at the source.
        if original.animal_cost_allocations:
            return 'This expense is split across animals. Void it and record it again to change the amount.'
        if original.source_document_type or (original.reference_code or '').startswith('PAYROLL-'):
            return 'This entry was posted automatically (stock, payroll or advances). Correct the amount at its source.'
        return None
