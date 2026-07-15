from __future__ import annotations

from decimal import Decimal

from app import create_app, db
from config import Config
from app.models.supply import InventoryItem
from app.services.inventory_standards_service import InventoryStandardsService


def _all_zero(item: InventoryItem) -> bool:
    return (
        Decimal(str(item.energy_mj_per_kg or 0)) == 0
        and Decimal(str(item.protein_grams_per_kg or 0)) == 0
        and Decimal(str(item.fiber_grams_per_kg or 0)) == 0
        and Decimal(str(item.cost_per_kg or 0)) == 0
    )


def run_backfill() -> None:
    app = create_app(Config)
    updated = 0
    skipped = 0

    with app.app_context():
        rows = InventoryItem.query.order_by(InventoryItem.id.asc()).all()
        for item in rows:
            if (item.category or '').strip().lower() != 'bulk feed':
                skipped += 1
                continue

            if not _all_zero(item):
                skipped += 1
                continue

            payload = InventoryStandardsService.apply_defaults(
                name=item.name,
                category=item.category,
                energy_mj_per_kg=None,
                protein_grams_per_kg=None,
                fiber_grams_per_kg=None,
                cost_per_kg=None,
            )
            values = payload['values']

            item.energy_mj_per_kg = values['energy_mj_per_kg']
            item.protein_grams_per_kg = values['protein_grams_per_kg']
            item.fiber_grams_per_kg = values['fiber_grams_per_kg']
            item.cost_per_kg = values['cost_per_kg']
            updated += 1

        db.session.commit()

    print({'updated': updated, 'skipped': skipped})


if __name__ == '__main__':
    run_backfill()