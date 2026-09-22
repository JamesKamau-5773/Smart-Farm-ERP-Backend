"""Link employees to user accounts.

Revision ID: e9a1c3d5f7b2
Revises: d8f0b2c4e6a8
Create Date: 2026-09-21
"""

from alembic import op
import sqlalchemy as sa


revision = 'e9a1c3d5f7b2'
down_revision = 'd8f0b2c4e6a8'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('employees', sa.Column('user_id', sa.Integer(), nullable=True))
    op.create_foreign_key(
        'fk_employees_user_id_users',
        'employees',
        'users',
        ['user_id'],
        ['id'],
        ondelete='SET NULL',
    )
    op.create_unique_constraint('uq_employees_user_id', 'employees', ['user_id'])


def downgrade():
    op.drop_constraint('uq_employees_user_id', 'employees', type_='unique')
    op.drop_constraint('fk_employees_user_id_users', 'employees', type_='foreignkey')
    op.drop_column('employees', 'user_id')
