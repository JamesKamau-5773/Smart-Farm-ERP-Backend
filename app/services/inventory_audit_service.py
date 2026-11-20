"""What gets written to the audit log for inventory events."""
from __future__ import annotations

from app.models.supply import InventoryItem, InventoryTransaction
from app.services.audit_service import record_request_audit

ITEM_FIELDS = (
    'name', 'sku', 'category', 'unit', 'minimum_threshold', 'protein_grams_per_kg',
    'energy_mj_per_kg', 'fiber_grams_per_kg', 'cost_per_kg', 'is_active',
)


def item_snapshot(item: InventoryItem) -> dict:
    return {field: getattr(item, field, None) for field in ITEM_FIELDS}


class InventoryAuditService:
    @staticmethod
    def stage_movement(item: InventoryItem, movement: InventoryTransaction, *, supplier_name=None, ledger_entry=None) -> None:
        """Staged in the movement's unit of work so both are saved together."""
        record_request_audit(
            f'INVENTORY_{movement.transaction_type}',
            'InventoryItem',
            item.id,
            new_value={
                'movement_id': movement.id,
                'reason_code': movement.reason_code,
                'quantity': movement.quantity,
                'unit_cost': movement.unit_cost,
                'supplier_name': supplier_name,
                'ledger_entry_id': ledger_entry.id if ledger_entry is not None else None,
                'balance_after': item.current_qty,
                'cost_per_kg_after': item.cost_per_kg,
            },
            commit=False,
        )

    @staticmethod
    def item_created(item: InventoryItem) -> None:
        record_request_audit('INVENTORY_ITEM_CREATE', 'InventoryItem', item.id, new_value=item_snapshot(item))

    @staticmethod
    def item_updated(item: InventoryItem, before: dict) -> None:
        after = item_snapshot(item)
        changed = {key: value for key, value in after.items() if before.get(key) != value}
        if changed:
            record_request_audit(
                'INVENTORY_ITEM_UPDATE', 'InventoryItem', item.id,
                old_value={key: before.get(key) for key in changed}, new_value=changed,
            )

    @staticmethod
    def item_deleted(item_id: int, before: dict) -> None:
        record_request_audit('INVENTORY_ITEM_DELETE', 'InventoryItem', item_id, old_value=before)

    @staticmethod
    def item_archive_changed(item: InventoryItem) -> None:
        action = 'INVENTORY_ITEM_RESTORE' if item.is_active else 'INVENTORY_ITEM_ARCHIVE'
        record_request_audit(action, 'InventoryItem', item.id, new_value={'is_active': item.is_active})
