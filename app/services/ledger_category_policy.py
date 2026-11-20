"""Which ledger categories a user may choose, and each expense's default cost class.

The one place these rules live: manual entry, corrections and the
``GET /finance/categories`` catalogue all read from here.
"""
from __future__ import annotations

from app.models.finance import CostClass, TransactionCategory, TransactionType

REVENUE_CATEGORIES = (
    TransactionCategory.MILK_SALE,
    TransactionCategory.LIVESTOCK_SALE,
    TransactionCategory.OTHER_INCOME,
    TransactionCategory.OTHER,
)

EXPENSE_CATEGORIES = (
    TransactionCategory.FEED_PURCHASE,
    TransactionCategory.VET_FEES,
    TransactionCategory.LABOR_WAGES,
    TransactionCategory.UTILITIES,
    TransactionCategory.EQUIPMENT_MAINTENANCE,
    TransactionCategory.TRANSPORT,
    TransactionCategory.OPENING_BALANCE,
    TransactionCategory.INVENTORY_WRITE_OFF,
    TransactionCategory.OTHER,
)

DEFAULT_COST_CLASS_BY_CATEGORY = {
    TransactionCategory.FEED_PURCHASE: CostClass.COGS,
    TransactionCategory.VET_FEES: CostClass.COGS,
    # Posted by the breeding workflow rather than chosen by hand.
    TransactionCategory.AI_SERVICE: CostClass.COGS,
    TransactionCategory.INVENTORY_WRITE_OFF: CostClass.COGS,
    # Farm overhead (power, water, permanent staff), not tied to particular cows.
    TransactionCategory.LABOR_WAGES: CostClass.OPERATING,
    TransactionCategory.UTILITIES: CostClass.OPERATING,
    TransactionCategory.EQUIPMENT_MAINTENANCE: CostClass.OPERATING,
    TransactionCategory.TRANSPORT: CostClass.OPERATING,
    TransactionCategory.OPENING_BALANCE: CostClass.OPERATING,
    TransactionCategory.OTHER: CostClass.OPERATING,
}

COST_CLASS_LABELS = {
    CostClass.COGS: 'Production cost',
    CostClass.OPERATING: 'Operating cost',
    CostClass.CUSTOMER_ACQUISITION: 'Customer acquisition',
    CostClass.CAPITAL: 'Capital expenditure',
}


def categories_for(transaction_type: TransactionType) -> tuple:
    if transaction_type == TransactionType.REVENUE:
        return REVENUE_CATEGORIES
    if transaction_type == TransactionType.EXPENSE:
        return EXPENSE_CATEGORIES
    return ()


def default_cost_class(category: TransactionCategory) -> CostClass:
    return DEFAULT_COST_CLASS_BY_CATEGORY.get(category, CostClass.OPERATING)


def catalogue() -> dict:
    return {
        'revenue': [{'value': category.value, 'label': category.value} for category in REVENUE_CATEGORIES],
        'expense': [
            {'value': category.value, 'label': category.value, 'default_cost_class': default_cost_class(category).value}
            for category in EXPENSE_CATEGORIES
        ],
        'cost_classes': [{'value': cost_class.value, 'label': label} for cost_class, label in COST_CLASS_LABELS.items()],
    }
