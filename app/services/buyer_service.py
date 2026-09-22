"""Buyer service with financial integrity enforcement and audit logging."""

import json
import logging
from datetime import date as date_type
from decimal import Decimal
from typing import Optional, Dict, Any

from flask import g

from app import db
from app.models.finance import Buyer, BuyerAuditLog, SalesLedger, PaymentStatus, PaymentAllocation, TransactionCategory
from app.services.payment_service import PaymentService
from app.utils.jwt_payload import parse_public_int_id

logger = logging.getLogger(__name__)


class DuplicateBuyerError(Exception):
    """Raised when buyer with same name already exists in tenant."""
    pass


class BuyerService:
    """Enforces buyer financial integrity and audit trail."""

    @staticmethod
    def _parse_farm_id(farm_id: Optional[Any]) -> Optional[int]:
        """Parse farm_id from public ID format (e.g., 'farm_1' → 1) or int."""
        if farm_id is None:
            return None

        # If already an int, return it
        if isinstance(farm_id, int):
            return farm_id

        # If string, try to parse as public ID or direct int
        if isinstance(farm_id, str):
            try:
                # Try parsing as "farm_N" format
                return parse_public_int_id(farm_id, 'farm_')
            except (TypeError, ValueError):
                try:
                    # Try parsing as direct int
                    return int(farm_id)
                except (TypeError, ValueError):
                    return None

        return None

    @staticmethod
    def _get_performed_by() -> Optional[int]:
        """Extract user_id from Flask g context if available."""
        try:
            return int(g.get('user_id', None))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _audit_log(tenant_id: int, buyer_id: Optional[int], action: str,
                   previous_values: Optional[Dict] = None, new_values: Optional[Dict] = None):
        """Log buyer action to audit trail."""
        log_entry = BuyerAuditLog(
            tenant_id=tenant_id,
            buyer_id=buyer_id,
            action=action,
            previous_values=previous_values,
            new_values=new_values,
            performed_by=BuyerService._get_performed_by(),
        )
        db.session.add(log_entry)

    @staticmethod
    def _normalize_whatsapp(contact: Optional[str], whatsapp: Optional[str]) -> Optional[str]:
        """Derive whatsapp from contact if not explicitly provided."""
        if whatsapp and str(whatsapp).strip():
            return str(whatsapp).strip()
        if contact and str(contact).strip():
            return str(contact).strip()
        return None

    @staticmethod
    def create_buyer(
        tenant_id: int,
        name: str,
        agreed_rate_per_liter: float,
        contact: Optional[str] = None,
        whatsapp: Optional[str] = None,
        buyer_type: str = "Individual",
        farm_id: Optional[int] = None,
        opening_balance: Optional[float] = None,
    ) -> Buyer:
        """
        Create buyer with validation and audit trail.

        Rules enforced:
        - name and agreed_rate_per_liter are required
        - balance/payment_status cannot be set directly; use opening_balance
        - whatsapp defaults to contact if not provided
        - Creates opening balance as ledger entry if provided

        Raises:
        - ValueError: For validation errors
        - DuplicateBuyerError: If buyer name already exists in tenant
        """
        name = (name or "").strip()
        if not name:
            raise ValueError("name is required and cannot be empty")

        if agreed_rate_per_liter is None:
            raise ValueError("agreed_rate_per_liter is required")

        try:
            rate = float(agreed_rate_per_liter)
            if rate <= 0:
                raise ValueError("agreed_rate_per_liter must be positive")
        except (TypeError, ValueError) as e:
            if "required" in str(e):
                raise
            raise ValueError(f"agreed_rate_per_liter must be a positive number: {str(e)}")

        # Check uniqueness within tenant
        existing = Buyer.query.filter_by(
            tenant_id=tenant_id,
            name=name,
            is_active=True
        ).first()
        if existing:
            raise DuplicateBuyerError(f"Buyer '{name}' already exists for this tenant")

        contact = (contact or "").strip() or None
        whatsapp_val = BuyerService._normalize_whatsapp(contact, whatsapp)
        buyer_type_val = (buyer_type or "Individual").strip()
        farm_id_parsed = BuyerService._parse_farm_id(farm_id)

        # Create buyer
        buyer = Buyer(
            tenant_id=tenant_id,
            farm_id=farm_id_parsed,
            name=name,
            phone_number=contact,
            whatsapp=whatsapp_val,
            buyer_type=buyer_type_val,
            agreed_rate_per_liter=rate,
            is_active=True,
        )
        db.session.add(buyer)
        db.session.flush()  # Get buyer.id before creating ledger entry

        # Audit log buyer creation
        BuyerService._audit_log(
            tenant_id=tenant_id,
            buyer_id=buyer.id,
            action="create",
            new_values={
                "name": buyer.name,
                "contact": buyer.phone_number,
                "whatsapp": buyer.whatsapp,
                "buyer_type": buyer.buyer_type,
                "agreed_rate_per_liter": float(buyer.agreed_rate_per_liter),
            }
        )

        # Handle opening balance as ledger entry
        if opening_balance and opening_balance != 0:
            try:
                opening_amount = float(opening_balance)
                if opening_amount < 0:
                    raise ValueError("opening_balance must be >= 0")

                logger.info(f"Processing opening_balance for buyer {buyer.id}: {opening_amount}")

                # Create opening balance ledger entry
                ledger_entry = SalesLedger(
                    tenant_id=tenant_id,
                    buyer_id=buyer.id,
                    date=date_type.today(),
                    shift="Opening",
                    liters_sold=Decimal(0),
                    total_cost=Decimal(str(opening_amount)),
                    payment_status=PaymentStatus.UNPAID,
                )
                db.session.add(ledger_entry)

                # Audit log opening balance
                BuyerService._audit_log(
                    tenant_id=tenant_id,
                    buyer_id=buyer.id,
                    action="opening_balance",
                    new_values={"opening_balance": opening_amount}
                )
                logger.info(f"Created opening balance ledger entry for buyer {buyer.id}: {opening_amount}")
            except (TypeError, ValueError) as e:
                db.session.rollback()
                raise ValueError(f"Invalid opening_balance: {str(e)}")
        else:
            logger.info(f"Skipping opening_balance for buyer {buyer.id}: value={opening_balance}")

        db.session.commit()
        logger.info(f"Created buyer {buyer.id} ({name}) for tenant {tenant_id}")
        return buyer

    @staticmethod
    def update_buyer(
        buyer_id: int,
        tenant_id: int,
        name: Optional[str] = None,
        contact: Optional[str] = None,
        whatsapp: Optional[str] = None,
        buyer_type: Optional[str] = None,
        agreed_rate_per_liter: Optional[float] = None,
        is_active: Optional[bool] = None,
        # REJECT these if provided
        balance: Optional[float] = None,
        current_balance: Optional[float] = None,
        payment_status: Optional[str] = None,
    ) -> Buyer:
        """
        Update buyer with validation and audit trail.

        Rules enforced:
        - Rejects balance, current_balance, payment_status (must use ledger)
        - whatsapp defaults to contact if not provided
        - Logs all changes to audit trail
        """
        # Reject client-computed financial state
        if balance is not None or current_balance is not None or payment_status is not None:
            raise ValueError(
                "Cannot set balance, current_balance, or payment_status directly. "
                "Use ledger entries instead."
            )

        buyer = Buyer.query.filter_by(id=buyer_id, tenant_id=tenant_id).first()
        if not buyer:
            raise ValueError("Buyer not found for this tenant")

        # Track previous values for audit
        previous_values = {
            "name": buyer.name,
            "contact": buyer.phone_number,
            "whatsapp": buyer.whatsapp,
            "buyer_type": buyer.buyer_type,
            "agreed_rate_per_liter": float(buyer.agreed_rate_per_liter),
            "is_active": buyer.is_active,
        }

        # Apply updates
        if name is not None:
            name_str = (name or "").strip()
            if not name_str:
                raise ValueError("name cannot be empty")
            # Check uniqueness
            existing = Buyer.query.filter(
                Buyer.tenant_id == tenant_id,
                Buyer.name == name_str,
                Buyer.id != buyer_id,
                Buyer.is_active == True
            ).first()
            if existing:
                raise ValueError(f"Buyer '{name_str}' already exists for this tenant")
            buyer.name = name_str

        if contact is not None:
            buyer.phone_number = (contact or "").strip() or None

        if whatsapp is not None or contact is not None:
            buyer.whatsapp = BuyerService._normalize_whatsapp(buyer.phone_number, whatsapp)

        if buyer_type is not None:
            buyer.buyer_type = (buyer_type or "Individual").strip()

        if agreed_rate_per_liter is not None:
            try:
                rate = float(agreed_rate_per_liter)
                if rate <= 0:
                    raise ValueError("agreed_rate_per_liter must be positive")
                buyer.agreed_rate_per_liter = rate
            except (TypeError, ValueError) as e:
                raise ValueError(f"Invalid agreed_rate_per_liter: {str(e)}")

        if is_active is not None:
            buyer.is_active = bool(is_active)

        # Track new values for audit
        new_values = {
            "name": buyer.name,
            "contact": buyer.phone_number,
            "whatsapp": buyer.whatsapp,
            "buyer_type": buyer.buyer_type,
            "agreed_rate_per_liter": float(buyer.agreed_rate_per_liter),
            "is_active": buyer.is_active,
        }

        # Audit log update
        BuyerService._audit_log(
            tenant_id=tenant_id,
            buyer_id=buyer_id,
            action="update",
            previous_values=previous_values,
            new_values=new_values,
        )

        db.session.commit()
        logger.info(f"Updated buyer {buyer_id} for tenant {tenant_id}")
        return buyer

    @staticmethod
    def delete_buyer(buyer_id: int, tenant_id: int, force: bool = False) -> bool:
        """
        Delete buyer with safety checks.

        Rules enforced:
        - Prefers soft delete (is_active=False) if buyer has ledger history
        - Hard delete only if no financial references exist and force=True
        - Logs deletion to audit trail
        """
        buyer = Buyer.query.filter_by(id=buyer_id, tenant_id=tenant_id).first()
        if not buyer:
            raise ValueError("Buyer not found for this tenant")

        # Check if buyer has any ledger entries
        has_ledger = SalesLedger.query.filter_by(
            buyer_id=buyer_id,
            tenant_id=tenant_id
        ).first() is not None

        if has_ledger and not force:
            # Soft delete
            buyer.is_active = False
            BuyerService._audit_log(
                tenant_id=tenant_id,
                buyer_id=buyer_id,
                action="soft_delete",
                previous_values={"is_active": True},
                new_values={"is_active": False}
            )
            db.session.commit()
            logger.info(f"Soft-deleted buyer {buyer_id} (has ledger history)")
            return False  # Soft delete

        # Hard delete only if force or no ledger
        if force or not has_ledger:
            previous_values = {
                "name": buyer.name,
                "contact": buyer.phone_number,
                "buyer_type": buyer.buyer_type,
            }
            BuyerService._audit_log(
                tenant_id=tenant_id,
                buyer_id=buyer_id,
                action="hard_delete",
                previous_values=previous_values,
            )
            db.session.delete(buyer)
            db.session.commit()
            logger.info(f"Hard-deleted buyer {buyer_id}")
            return True  # Hard delete

        raise ValueError("Cannot delete buyer with ledger history without force=True")

    @staticmethod
    def get_buyer_balance(buyer_id: int, tenant_id: int) -> float:
        """Calculate current balance from ledger (source of truth)."""
        result = db.session.query(
            db.func.coalesce(db.func.sum(SalesLedger.total_cost - SalesLedger.amount_paid), 0)
        ).filter(
            SalesLedger.buyer_id == buyer_id,
            SalesLedger.tenant_id == tenant_id,
            SalesLedger.payment_status != PaymentStatus.PAID,
        ).scalar()
        return float(result or 0)

    @staticmethod
    def serialize_buyer(buyer: Buyer) -> Dict[str, Any]:
        """Return consistent buyer response shape (excludes client-writable fields)."""
        balance = BuyerService.get_buyer_balance(buyer.id, buyer.tenant_id)
        return {
            "id": buyer.id,
            "name": buyer.name,
            "contact": buyer.phone_number,
            "whatsapp": buyer.whatsapp,
            "buyer_type": buyer.buyer_type,
            "type": buyer.buyer_type,  # Alias
            "agreed_rate_per_liter": float(buyer.agreed_rate_per_liter),
            "rate_per_liter": float(buyer.agreed_rate_per_liter),  # Alias
            "current_balance": balance,
            "payment_status": PaymentStatus.PAID if balance == 0 else PaymentStatus.UNPAID,
            "is_active": buyer.is_active,
            "farm_id": buyer.farm_id,
        }

    @staticmethod
    def allocate_payment(
        buyer_id: int,
        tenant_id: int,
        amount: float,
        note: Optional[str] = None,
        reference_code: Optional[str] = None,
        recorded_by: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Create a payment transaction and allocate it against the buyer's oldest unpaid sales."""
        buyer = Buyer.query.filter_by(id=buyer_id, tenant_id=tenant_id).first()
        if not buyer:
            raise ValueError("Buyer not found for this tenant")

        try:
            payment_amount = Decimal(str(amount))
        except Exception as exc:
            raise ValueError("amount must be a valid number") from exc

        if payment_amount <= 0:
            raise ValueError("amount must be greater than 0")

        previous_balance = Decimal(str(BuyerService.get_buyer_balance(buyer_id, tenant_id)))
        if previous_balance <= 0:
            raise ValueError("Buyer has no unpaid balance")
        if payment_amount > previous_balance:
            raise ValueError("Payment amount exceeds buyer outstanding balance")

        # 1. Create the master Transaction for the full payment amount.
        tx = PaymentService.create_payment_transaction(
            tenant_id=tenant_id,
            buyer_id=buyer_id,
            category=TransactionCategory.BUYER_PAYMENT,
            amount=payment_amount,
            description=note or f'Payment from buyer #{buyer_id}',
            reference_code=reference_code,
            recorded_by=recorded_by,
        )
        db.session.flush()  # Flush to get the new transaction ID (tx.id)
        from app.services.receipt_service import ReceiptService
        ReceiptService.issue(tx, issued_by=recorded_by)

        # 2. Fetch all UNPAID or PARTIALLY_PAID sales, oldest first (FIFO).
        unpaid_rows = (
            SalesLedger.query.filter_by(
                tenant_id=tenant_id,
                buyer_id=buyer_id,
            )
            .filter(SalesLedger.payment_status.in_([PaymentStatus.UNPAID, PaymentStatus.PARTIALLY_PAID]))
            .order_by(SalesLedger.date.asc(), SalesLedger.id.asc())
            .all()
        )

        amount_remaining_to_allocate = payment_amount
        allocations_made = []

        # 3. Waterfall the payment across the oldest sales.
        for row in unpaid_rows:
            if amount_remaining_to_allocate <= 0:
                break

            owed_on_sale = Decimal(row.total_cost)
            if owed_on_sale <= 0:
                continue

            apply_amount = min(amount_remaining_to_allocate, owed_on_sale)

            # Create the bridge record linking the transaction to the sale.
            allocation = PaymentAllocation(
                tenant_id=tenant_id,
                transaction_id=tx.id,
                sales_ledger_id=row.id,
                amount_applied=apply_amount,
            )
            db.session.add(allocation)

            # Update the sale's payment tracker and status.
            row.total_cost -= apply_amount
            if row.total_cost <= 0:
                row.total_cost = Decimal('0')
                row.payment_status = PaymentStatus.PAID
            else:
                row.payment_status = PaymentStatus.UNPAID

            # Explicitly add the modified row to the session to ensure it's tracked for commit.
            db.session.add(row)

            allocations_made.append(
                {
                    "sales_ledger_id": row.id,
                    "date": row.date.isoformat() if row.date else None,
                    "applied_amount": float(apply_amount),
                    "remaining_on_entry": float(row.total_cost),
                    "payment_status": row.payment_status,
                }
            )
            amount_remaining_to_allocate -= apply_amount

        applied_total = payment_amount - amount_remaining_to_allocate
        current_balance = previous_balance - applied_total

        BuyerService._audit_log(
            tenant_id=tenant_id,
            buyer_id=buyer_id,
            action="payment_received",
            new_values={
                "amount": float(payment_amount),
                "applied_amount": float(applied_total),
                "unallocated_credit": float(amount_remaining_to_allocate),
                "note": note,
                "transaction_id": tx.id,
            },
        )

        # The single, atomic commit for the entire operation.
        db.session.commit()

        return {
            "buyer": buyer,
            "transaction": tx,
            "applied_amount": float(applied_total),
            "unallocated_credit": float(amount_remaining_to_allocate),
            "previous_balance": float(previous_balance),
            "current_balance": float(current_balance),
            "allocations": allocations_made,
        }
