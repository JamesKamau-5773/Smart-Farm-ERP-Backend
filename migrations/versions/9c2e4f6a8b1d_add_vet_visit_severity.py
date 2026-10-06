"""Add persisted severity to vet visits.

Revision ID: 9c2e4f6a8b1d
Revises: 4a79e041ba7f
"""
from alembic import op
import sqlalchemy as sa


revision = '9c2e4f6a8b1d'
down_revision = '943215af98d1'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'vet_visits',
        sa.Column('severity', sa.String(length=10), server_default='Medium', nullable=False),
    )
    op.create_check_constraint(
        'ck_vet_visits_severity_valid',
        'vet_visits',
        "severity IN ('Low', 'Medium', 'High')",
    )


def downgrade():
    op.drop_constraint('ck_vet_visits_severity_valid', 'vet_visits', type_='check')
    op.drop_column('vet_visits', 'severity')
