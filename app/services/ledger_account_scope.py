"""Turns the ledger's account filters (explicit account or name search) into account ids."""
from __future__ import annotations

from dataclasses import dataclass, field

from app import db
from app.models.finance import Buyer, Customer
from app.schemas.ledger_filters import LedgerFilters
from app.services.request_scope import FarmScope
from app.utils.api_errors import ApiError
from app.utils.fuzzy_search import match_names


@dataclass(frozen=True)
class AccountScope:
    customer_ids: list[int] | None = None  # None = not narrowed by account
    buyer_ids: list[int] | None = None
    mode: str = 'all'
    typo_matched: bool = False
    matched_names: list[str] = field(default_factory=list)

    @property
    def is_narrowed(self) -> bool:
        return self.customer_ids is not None or self.buyer_ids is not None


class LedgerAccountScopeResolver:
    @staticmethod
    def resolve(scope: FarmScope, filters: LedgerFilters) -> AccountScope:
        if filters.account_type == 'customer':
            customer = Customer.query.filter_by(id=filters.account_id, tenant_id=scope.tenant_id).first()
            if not customer:
                raise ApiError('NOT_FOUND', 'Customer not found.', status=404)
            return AccountScope(customer_ids=[customer.id], buyer_ids=[], mode='account')
        if filters.account_type == 'buyer':
            buyer_query = Buyer.query.filter_by(id=filters.account_id, tenant_id=scope.tenant_id)
            if scope.farm_id is not None:
                buyer_query = buyer_query.filter(Buyer.farm_id == scope.farm_id)
            buyer = buyer_query.first()
            if not buyer:
                raise ApiError('NOT_FOUND', 'Buyer not found.', status=404)
            return AccountScope(customer_ids=[], buyer_ids=[buyer.id], mode='account')
        if filters.search:
            return LedgerAccountScopeResolver._search(scope, filters.search)
        return AccountScope()

    @staticmethod
    def _search(scope: FarmScope, search: str) -> AccountScope:
        # Typo-tolerant: exact/compact matches first, otherwise the closest names (e.g. "Njeru"
        # finds "Mama Njeri Hotel"). Account lists per tenant are small, so match in Python.
        customer_rows = db.session.query(Customer.id, Customer.name).filter(Customer.tenant_id == scope.tenant_id).all()
        buyer_query = db.session.query(Buyer.id, Buyer.name).filter(Buyer.tenant_id == scope.tenant_id)
        if scope.farm_id is not None:
            buyer_query = buyer_query.filter(Buyer.farm_id == scope.farm_id)
        buyer_rows = buyer_query.all()

        customer_ids, customer_typo = match_names(customer_rows, search)
        buyer_ids, buyer_typo = match_names(buyer_rows, search)
        typo_matched = False
        matched_names: list[str] = []
        if customer_ids or buyer_ids:
            # Only report a typo match when no exact match was found on either side.
            typo_matched = (customer_typo or not customer_ids) and (buyer_typo or not buyer_ids)
            if typo_matched:
                matched = set(customer_ids) | set(buyer_ids)
                matched_names = sorted({name for row_id, name in [*customer_rows, *buyer_rows] if row_id in matched})
        return AccountScope(
            customer_ids=customer_ids,
            buyer_ids=buyer_ids,
            mode='search',
            typo_matched=typo_matched,
            matched_names=matched_names,
        )
