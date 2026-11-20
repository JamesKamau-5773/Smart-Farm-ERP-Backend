"""Ledger list filters, shared by ``GET /ledger`` and every ledger total.

Parsing lives here once, so the list, its KPI cards and the period totals can
never accept different filters.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from app.models.finance import TransactionCategory, TransactionType
from app.services import ledger_classification
from app.utils.api_errors import ApiError


def _invalid(message: str) -> ApiError:
    return ApiError('VALIDATION_ERROR', message, status=400)


def _parse_date(args, *names: str) -> date | None:
    for name in names:
        raw = args.get(name)
        if raw in (None, ''):
            continue
        try:
            return datetime.fromisoformat(str(raw).split('T')[0]).date()
        except (TypeError, ValueError):
            raise _invalid(f'{name} must be a valid date in YYYY-MM-DD format.') from None
    return None


@dataclass(frozen=True)
class LedgerFilters:
    types: tuple[TransactionType, ...] | None = None
    category: TransactionCategory | None = None
    search: str | None = None
    account_type: str | None = None
    account_id: int | None = None
    date_from: date | None = None
    date_to: date | None = None

    @classmethod
    def from_args(cls, args) -> 'LedgerFilters':
        types = None
        raw_type = args.get('type')
        if raw_type not in (None, ''):
            types = ledger_classification.types_for_filter(raw_type)
            if types is None:
                raise _invalid('type must be income, expense, unpaid, credit or a ledger entry type.')

        category = None
        raw_category = args.get('category')
        if raw_category not in (None, ''):
            category = next((
                candidate for candidate in TransactionCategory
                if str(raw_category).strip().lower() in (candidate.value.lower(), candidate.name.lower())
            ), None)
            if category is None:
                raise _invalid('category is not a known ledger category.')

        search = str(args.get('search') or args.get('search_query') or '').strip() or None

        account_type = str(args.get('account_type') or '').strip().lower() or None
        account_id_raw = args.get('account_id')
        legacy_customer_id = args.get('customer_id')
        if legacy_customer_id not in (None, ''):
            if account_type or account_id_raw not in (None, ''):
                raise _invalid('Use either customer_id or account_type/account_id, not both.')
            account_type, account_id_raw = 'customer', legacy_customer_id
        if search and (account_type or account_id_raw not in (None, '')):
            raise _invalid('Use either search_query or an explicit account scope, not both.')
        if bool(account_type) != (account_id_raw not in (None, '')):
            raise _invalid('account_type and account_id must be provided together.')
        if account_type and account_type not in ('customer', 'buyer'):
            raise _invalid('account_type must be customer or buyer.')
        account_id = None
        if account_id_raw not in (None, ''):
            if not str(account_id_raw).strip().isdigit():
                raise _invalid('account_id must be a valid integer.')
            account_id = int(str(account_id_raw).strip())

        date_from = _parse_date(args, 'date_from', 'start_date')
        date_to = _parse_date(args, 'date_to', 'end_date')
        if date_from and date_to and date_to < date_from:
            raise _invalid('date_to cannot be earlier than date_from.')

        return cls(
            types=types,
            category=category,
            search=search,
            account_type=account_type,
            account_id=account_id,
            date_from=date_from,
            date_to=date_to,
        )
