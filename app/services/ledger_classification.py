"""Which ledger entries count as income, expenses, unpaid charges and credits.

The one place these rules live. The ledger KPI cards, the period summary, the
group totals and the dashboard's daily figures all build their sums from here,
so they reconcile by construction.

Rules (cash basis):
- Only POSTED entries count. DRAFT and VOIDED entries are listed but never totalled.
- income   = Revenue + Payment       (money that actually came in)
- expenses = Expense
- unpaid   = Debit                   (charged to a customer's account, not yet received)
- credit   = Credit                  (credit notes / price reductions on an account)
- net      = income - expenses       (unpaid and credit are reported separately, never in income)
- The entry type decides the direction, never the stored sign: some historical
  rows store expenses as negative amounts, so every bucket sums ABS(amount).
"""
from __future__ import annotations

import enum
from decimal import Decimal

from sqlalchemy import and_, case, func

from app.models.finance import Transaction, TransactionStatus, TransactionType


class LedgerBucket(str, enum.Enum):
    INCOME = 'income'
    EXPENSE = 'expense'
    UNPAID = 'unpaid'
    CREDIT = 'credit'


COUNTED_STATUSES = (TransactionStatus.POSTED.value,)

TYPES_BY_BUCKET: dict[LedgerBucket, tuple[TransactionType, ...]] = {
    LedgerBucket.INCOME: (TransactionType.REVENUE, TransactionType.PAYMENT),
    LedgerBucket.EXPENSE: (TransactionType.EXPENSE,),
    LedgerBucket.UNPAID: (TransactionType.DEBIT,),
    LedgerBucket.CREDIT: (TransactionType.CREDIT,),
}

BUCKET_BY_TYPE: dict[TransactionType, LedgerBucket] = {
    transaction_type: bucket
    for bucket, types in TYPES_BY_BUCKET.items()
    for transaction_type in types
}


def classify(transaction_type: TransactionType, status: str) -> LedgerBucket | None:
    """The bucket an entry contributes to, or None when it is not totalled."""
    if status not in COUNTED_STATUSES:
        return None
    return BUCKET_BY_TYPE.get(TransactionType(transaction_type))


def magnitude(amount) -> Decimal:
    """Size of an entry, regardless of the sign it was stored with."""
    return abs(Decimal(str(amount or 0)))


def bucket_sum(bucket: LedgerBucket):
    """SQL ``SUM`` of one bucket's amounts, counting only posted entries."""
    return func.coalesce(func.sum(case(
        (
            and_(
                Transaction.status.in_(COUNTED_STATUSES),
                Transaction.transaction_type.in_(TYPES_BY_BUCKET[bucket]),
            ),
            func.abs(Transaction.amount),
        ),
        else_=0,
    )), 0)


def types_for_filter(value: str) -> tuple[TransactionType, ...] | None:
    """Resolve a ``type`` filter: a bucket name (income/expense/unpaid/credit) or an entry type."""
    normalized = str(value or '').strip().lower()
    for bucket in LedgerBucket:
        if normalized == bucket.value or normalized == f'{bucket.value}s':
            return TYPES_BY_BUCKET[bucket]
    for transaction_type in TransactionType:
        if normalized in (transaction_type.value.lower(), transaction_type.name.lower()):
            return (transaction_type,)
    return None
