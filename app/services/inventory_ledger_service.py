"""Posts inventory events to the financial ledger.

Entries are added to the session but not committed, so the stock movement and
its ledger entry are saved together by the calling unit of work.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from app import db
from app.models.finance import CostClass, Transaction, TransactionCategory, TransactionType
from app.models.supply import InventoryItem, InventoryTransaction

SOURCE_DOCUMENT_TYPE = 'inventory_transaction'


class InventoryLedgerService:
    @staticmethod
    def post_purchase(
        *,
        tenant_id: int,
        item: InventoryItem,
        movement: InventoryTransaction,
        actor_id: Optional[int],
        supplier_name: Optional[str] = None,
    ) -> Optional[Transaction]:
        amount = Decimal(str(movement.quantity)) * Decimal(str(movement.unit_cost))
        return InventoryLedgerService._post(
            tenant_id=tenant_id,
            category=TransactionCategory.FEED_PURCHASE,
            amount=amount,
            item=item,
            movement=movement,
            actor_id=actor_id,
            description=f'Purchase of {movement.quantity} {item.unit} {item.name}'
                        + (f' from {supplier_name}' if supplier_name else ''),
            counterparty_name=supplier_name,
        )

    @staticmethod
    def post_write_off(
        *,
        tenant_id: int,
        item: InventoryItem,
        movement: InventoryTransaction,
        actor_id: Optional[int],
    ) -> Optional[Transaction]:
        amount = Decimal(str(movement.quantity)) * Decimal(str(item.cost_per_kg))
        return InventoryLedgerService._post(
            tenant_id=tenant_id,
            category=TransactionCategory.INVENTORY_WRITE_OFF,
            amount=amount,
            item=item,
            movement=movement,
            actor_id=actor_id,
            description=f'Inventory write-off for {item.name}: {movement.notes or movement.reason_code}',
        )

    @staticmethod
    def _post(*, tenant_id, category, amount, item, movement, actor_id, description, counterparty_name=None):
        amount = amount.quantize(Decimal('0.01'))
        if amount <= 0:
            return None
        now = datetime.now(timezone.utc)
        entry = Transaction(
            tenant_id=tenant_id,
            transaction_type=TransactionType.EXPENSE,
            category=category,
            cost_class=CostClass.COGS,
            amount=amount,
            item_name=item.name,
            quantity=movement.quantity,
            description=description,
            counterparty_name=counterparty_name,
            recorded_by=actor_id,
            posted_by=actor_id,
            posted_at=now,
            timestamp=now,
            source_document_type=SOURCE_DOCUMENT_TYPE,
            source_document_id=movement.id,
        )
        db.session.add(entry)
        return entry
