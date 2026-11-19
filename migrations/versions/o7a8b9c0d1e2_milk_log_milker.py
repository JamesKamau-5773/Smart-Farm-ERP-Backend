"""Record who milked the cow, apart from who entered the record (BR-019).

Revision ID: o7a8b9c0d1e2
Revises: n6f7a8b9c0d1
Create Date: 2026-11-17

* ``milk_logs.milker_employee_id``: the employee who milked, sent as ``milker_id`` and
  ``milker_name``. Null on existing rows; the list then names the person who entered it.
"""
from alembic import op
import sqlalchemy as sa


revision = 'o7a8b9c0d1e2'
down_revision = 'n6f7a8b9c0d1'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('milk_logs', sa.Column('milker_employee_id', sa.Integer(), nullable=True))
    op.create_foreign_key(
        'fk_milk_logs_milker_employee_id', 'milk_logs', 'employees',
        ['milker_employee_id'], ['id'], ondelete='SET NULL',
    )
    op.create_index('ix_milk_logs_milker_employee_id', 'milk_logs', ['milker_employee_id'])


def downgrade():
    op.drop_index('ix_milk_logs_milker_employee_id', table_name='milk_logs')
    op.drop_constraint('fk_milk_logs_milker_employee_id', 'milk_logs', type_='foreignkey')
    op.drop_column('milk_logs', 'milker_employee_id')
