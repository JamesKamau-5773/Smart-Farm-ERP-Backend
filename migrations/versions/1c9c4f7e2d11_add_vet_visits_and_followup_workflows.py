"""Add vet visits and follow-up workflows

Revision ID: 1c9c4f7e2d11
Revises: 7b1d2f6c9c31
Create Date: 2026-05-26 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '1c9c4f7e2d11'
down_revision = '7b1d2f6c9c31'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'vet_visits',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('tenant_id', sa.Integer(), nullable=False),
        sa.Column('animal_id', sa.Integer(), nullable=False),
        sa.Column('vet_id', sa.Integer(), nullable=False),
        sa.Column('visit_date', sa.Date(), nullable=False),
        sa.Column('reason_for_visit', sa.Text(), nullable=False),
        sa.Column('diagnosis', sa.Text(), nullable=True),
        sa.Column('medications', sa.JSON(), nullable=True),
        sa.Column('recommendations', sa.Text(), nullable=True),
        sa.Column('remarks', sa.Text(), nullable=True),
        sa.Column('observations', sa.Text(), nullable=True),
        sa.Column('follow_up_required', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('follow_up_date', sa.Date(), nullable=True),
        sa.Column('follow_up_status', sa.String(length=20), nullable=False, server_default='Not Required'),
        sa.Column('follow_up_completed_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.CheckConstraint("follow_up_status IN ('Not Required', 'Pending', 'Scheduled', 'Completed', 'Overdue', 'Cancelled')", name='ck_vet_visits_follow_up_status_valid'),
        sa.ForeignKeyConstraint(['animal_id'], ['cows.id']),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id']),
        sa.ForeignKeyConstraint(['vet_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_vet_visits_tenant_id', 'vet_visits', ['tenant_id'], unique=False)
    op.create_index('ix_vet_visits_animal_id', 'vet_visits', ['animal_id'], unique=False)
    op.create_index('ix_vet_visits_vet_id', 'vet_visits', ['vet_id'], unique=False)


def downgrade():
    op.drop_index('ix_vet_visits_vet_id', table_name='vet_visits')
    op.drop_index('ix_vet_visits_animal_id', table_name='vet_visits')
    op.drop_index('ix_vet_visits_tenant_id', table_name='vet_visits')
    op.drop_table('vet_visits')