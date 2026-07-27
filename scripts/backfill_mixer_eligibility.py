from __future__ import annotations

from app import create_app, db
from app.models.supply import InventoryItem
from app.services.feed_mixer_policy_service import FeedMixerPolicyService
from config import Config


def run_backfill(*, dry_run: bool = False) -> dict:
    app = create_app(Config)
    updated = 0
    skipped = 0

    with app.app_context():
        rows = InventoryItem.query.order_by(InventoryItem.id.asc()).all()
        for row in rows:
            policy = FeedMixerPolicyService.resolve_item_policy(row)
            allowed_mixers = ','.join(policy['allowed_mixers'])
            role = policy['role']

            changed = False
            if (row.allowed_mixers or '') != allowed_mixers:
                row.allowed_mixers = allowed_mixers
                changed = True
            if (row.mixer_role or '') != role:
                row.mixer_role = role
                changed = True

            # Keep existing percentage values unless null/missing.
            if row.inclusion_percentage_dairy_meal is None:
                row.inclusion_percentage_dairy_meal = 0
                changed = True
            if row.inclusion_percentage_main_meal is None:
                row.inclusion_percentage_main_meal = 0
                changed = True

            if changed:
                updated += 1
            else:
                skipped += 1

        if dry_run:
            db.session.rollback()
        else:
            db.session.commit()

    return {
        'updated': updated,
        'skipped': skipped,
        'dry_run': dry_run,
    }


if __name__ == '__main__':
    result = run_backfill(dry_run=False)
    print(result)
