"""backfill receipt farm snapshots

Revision ID: c2a91e7d4f08
Revises: b7d4e2a19c63
"""

from alembic import op


revision = 'c2a91e7d4f08'
down_revision = 'b7d4e2a19c63'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        UPDATE transactions t
        SET farm_id = (
            SELECT f.id FROM farms f
            WHERE f.tenant_id = t.tenant_id
            ORDER BY f.is_active DESC, f.id
            LIMIT 1
        )
        WHERE t.farm_id IS NULL
          AND EXISTS (SELECT 1 FROM farms f WHERE f.tenant_id = t.tenant_id)
    """)
    op.execute('DROP TRIGGER IF EXISTS receipts_immutable ON receipts')
    op.execute("""
        UPDATE receipts r
        SET farm_id = t.farm_id,
            snapshot = r.snapshot || jsonb_build_object(
                'farm', jsonb_build_object('id', f.id, 'name', f.name),
                'transaction_status', COALESCE(t.status, 'POSTED'),
                'currency', COALESCE(r.currency, 'KES')
            )
        FROM transactions t
        JOIN farms f ON f.id = t.farm_id
        WHERE r.transaction_id = t.id
          AND r.farm_id IS NULL
    """)
    op.execute("""
        CREATE TRIGGER receipts_immutable
        BEFORE UPDATE OR DELETE ON receipts
        FOR EACH ROW EXECUTE FUNCTION prevent_receipt_mutation();
    """)


def downgrade():
    pass
