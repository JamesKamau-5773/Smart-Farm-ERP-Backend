"""Record how each milk entry arrived, and store sessions in one spelling (BR-019).

Revision ID: m5e6f7a8b9c0
Revises: l4d5e6f7a8b9
Create Date: 2026-11-12

* ``milk_logs.source`` ('app' | 'whatsapp' | 'import'), sent as ``recorded_via``. Existing
  WhatsApp entries are found through their WHATSAPP_LOG_MILK audit rows; the rest stay 'app'.
* Sessions are stored as Morning / Midday / Evening. Other casings are rewritten; WhatsApp's
  "Afternoon" maps to Midday, as the WhatsApp flow already does. Anything else is left alone.
"""
from alembic import op
import sqlalchemy as sa


revision = 'm5e6f7a8b9c0'
down_revision = 'l4d5e6f7a8b9'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'milk_logs',
        sa.Column('source', sa.String(length=20), nullable=False, server_default='app'),
    )
    op.create_check_constraint(
        'ck_milk_logs_source_valid', 'milk_logs', "source IN ('app', 'whatsapp', 'import')",
    )
    op.execute(
        """
        UPDATE milk_logs SET source = 'whatsapp'
        WHERE id IN (
            SELECT entity_id FROM audit_logs
            WHERE action = 'WHATSAPP_LOG_MILK' AND entity_type = 'MilkLog'
        )
        """
    )
    op.execute(
        """
        UPDATE milk_logs SET session = CASE lower(trim(session))
            WHEN 'morning' THEN 'Morning'
            WHEN 'midday' THEN 'Midday'
            WHEN 'afternoon' THEN 'Midday'
            WHEN 'evening' THEN 'Evening'
        END
        WHERE lower(trim(session)) IN ('morning', 'midday', 'afternoon', 'evening')
          AND session NOT IN ('Morning', 'Midday', 'Evening')
        """
    )


def downgrade():
    # Session spellings are not restored; the canonical form is valid for older code too.
    op.drop_constraint('ck_milk_logs_source_valid', 'milk_logs', type_='check')
    op.drop_column('milk_logs', 'source')
