"""Records stock movements together with their side effects, atomically.

* Receiving: a delivery may carry a price (updates weighted-average cost), a
  supplier (recorded as a delivery lot, ``InventoryBatch``) and, when the
  farmer asks for it, a feed-purchase expense in the ledger.
* Issuing: a write-off (spoilage, spill, stock-count loss, ...) also posts an inventory write-off expense.

Either the movement and its side effects are all saved, or none are.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from sqlalchemy.exc import SQLAlchemyError

from app import db
from app.models.finance import Transaction
from app.models.supply import InventoryBatch, InventoryItem, InventoryTransaction
from app.repositories.supply_repo import InventoryRepository
from app.services.inventory_audit_service import InventoryAuditService
from app.services.inventory_ledger_service import InventoryLedgerService
from app.utils.farm_time import farm_today

# Reasons a user can give for stock lost before it was fed.
LOSS_REASONS = frozenset({'SPOILAGE', 'SPILL', 'EXPIRED', 'DAMAGE', 'SHRINKAGE'})
# Stock that leaves without being fed is a loss and is expensed as a write-off.
WRITE_OFF_REASONS = LOSS_REASONS | {'AUDIT_LOSS'}


@dataclass(frozen=True)
class Delivery:
    item_id: int
    quantity: object
    unit_cost: object = None
    supplier_name: Optional[str] = None
    record_expense: bool = False
    notes: Optional[str] = None
    reason_code: str = 'STANDARD'


@dataclass(frozen=True)
class Issue:
    item_id: int
    quantity: object
    reason_code: str
    notes: Optional[str] = None


@dataclass(frozen=True)
class RecordedMovement:
    item: InventoryItem
    movement: InventoryTransaction
    is_low_stock: bool
    lot: Optional[InventoryBatch]
    ledger_entry: Optional[Transaction]


class InventoryMovementService:
    @staticmethod
    def receive(tenant_id: int, delivery: Delivery, *, actor_id: Optional[int]) -> RecordedMovement:
        supplier = (delivery.supplier_name or '').strip() or None
        if delivery.record_expense and delivery.unit_cost in (None, ''):
            raise ValueError('unit_cost is required to record this delivery as an expense.')
        if supplier and len(supplier) > 100:
            raise ValueError('supplier_name must be at most 100 characters.')

        try:
            item, movement, is_low_stock = InventoryRepository.record_transaction(
                item_id=delivery.item_id,
                transaction_type='IN',
                quantity=delivery.quantity,
                reason_code=delivery.reason_code,
                unit_cost=delivery.unit_cost,
                logged_by=actor_id,
                notes=delivery.notes,
                tenant_id=tenant_id,
                commit=False,
            )
            lot = None
            if supplier:
                lot = InventoryMovementService._attach_lot(tenant_id, item, movement, supplier)
            ledger_entry = None
            if delivery.record_expense:
                ledger_entry = InventoryLedgerService.post_purchase(
                    tenant_id=tenant_id, item=item, movement=movement,
                    actor_id=actor_id, supplier_name=supplier,
                )
            db.session.flush()
            InventoryAuditService.stage_movement(item, movement, supplier_name=supplier, ledger_entry=ledger_entry)
            db.session.commit()
        except (ValueError, SQLAlchemyError):
            db.session.rollback()
            raise

        return RecordedMovement(item=item, movement=movement, is_low_stock=is_low_stock, lot=lot, ledger_entry=ledger_entry)

    @staticmethod
    def issue(tenant_id: int, issue: Issue, *, actor_id: Optional[int]) -> RecordedMovement:
        try:
            item, movement, is_low_stock = InventoryRepository.record_transaction(
                item_id=issue.item_id,
                transaction_type='OUT',
                quantity=issue.quantity,
                reason_code=issue.reason_code,
                logged_by=actor_id,
                notes=issue.notes,
                tenant_id=tenant_id,
                commit=False,
            )
            ledger_entry = None
            if issue.reason_code in WRITE_OFF_REASONS:
                ledger_entry = InventoryLedgerService.post_write_off(
                    tenant_id=tenant_id, item=item, movement=movement, actor_id=actor_id,
                )
            db.session.flush()
            InventoryAuditService.stage_movement(item, movement, ledger_entry=ledger_entry)
            db.session.commit()
        except (ValueError, SQLAlchemyError):
            db.session.rollback()
            raise
        return RecordedMovement(item=item, movement=movement, is_low_stock=is_low_stock, lot=None, ledger_entry=ledger_entry)

    @staticmethod
    def _attach_lot(tenant_id: int, item: InventoryItem, movement: InventoryTransaction, supplier: str) -> InventoryBatch:
        """One lot per item, supplier and farm day; repeat deliveries add to it."""
        received_on = farm_today()
        quantity = Decimal(str(movement.quantity))
        unit_cost = Decimal(str(movement.unit_cost))
        lot = InventoryBatch.query.filter_by(
            tenant_id=tenant_id, item_id=item.id, supplier_name=supplier, received_date=received_on,
        ).first()
        if lot is None:
            lot = InventoryBatch(
                tenant_id=tenant_id,
                item_id=item.id,
                supplier_name=supplier,
                received_quantity_kg=quantity,
                cost_per_kg=unit_cost,
                actual_protein_percentage=(Decimal(str(item.protein_grams_per_kg or 0)) / 10).quantize(Decimal('0.01')),
                received_date=received_on,
            )
            db.session.add(lot)
        else:
            previous_qty = Decimal(str(lot.received_quantity_kg))
            total_qty = previous_qty + quantity
            lot.cost_per_kg = (
                (previous_qty * Decimal(str(lot.cost_per_kg)) + quantity * unit_cost) / total_qty
            ).quantize(Decimal('0.01'))
            lot.received_quantity_kg = total_qty
        db.session.flush()
        movement.inventory_batch_id = lot.id
        return lot
