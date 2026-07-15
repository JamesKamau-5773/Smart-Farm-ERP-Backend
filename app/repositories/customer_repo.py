from __future__ import annotations
from flask import g, has_app_context

from app.models.finance import Customer
from app import db
from sqlalchemy.exc import SQLAlchemyError
from app.utils.jwt_payload import parse_public_int_id


def _resolve_tenant_id(tenant_id: int | None = None) -> int | None:
    if tenant_id is not None:
        return tenant_id
    if has_app_context():
        tenant_public_id = getattr(g, 'tenant_id', None)
        if tenant_public_id:
            try:
                return parse_public_int_id(tenant_public_id, 'tenant_')
            except (TypeError, ValueError):
                return None
    return None

class CustomerRepository:
    @staticmethod
    def get_by_phone(phone_number: str, tenant_id: int | None = None) -> Customer:
        """Fetches a customer using the standard 2547XXXXXXXX format."""
        resolved_tenant_id = _resolve_tenant_id(tenant_id)
        query = Customer.query.filter_by(phone_number=phone_number)
        if resolved_tenant_id is not None:
            query = query.filter_by(tenant_id=resolved_tenant_id)
        return query.first()

    @staticmethod
    def credit_account(customer_id: int, amount: float, tenant_id: int | None = None) -> Customer:
        """Reduces the customer's outstanding balance."""
        try:
            resolved_tenant_id = _resolve_tenant_id(tenant_id)
            if resolved_tenant_id is None:
                customer = db.session.get(Customer, customer_id)
            else:
                customer = Customer.query.filter_by(id=customer_id, tenant_id=resolved_tenant_id).first()
            if customer:
                # Assuming account_balance tracks what they owe. 
                # A payment reduces this balance.
                customer.account_balance -= amount
                db.session.commit()
            return customer
        except SQLAlchemyError as e:
            db.session.rollback()
            raise Exception("Database error while crediting customer account.")