"""Make cow tag number unique per tenant

Revision ID: 9c2a1f4e6b8d
Revises: e7b1c2d3f4a5
Create Date: 2026-07-03 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = '9c2a1f4e6b8d'
down_revision = 'e7b1c2d3f4a5'
branch_labels = None
depends_on = None


def _table_exists(conn, table_name: str) -> bool:
    return conn.execute(sa.text("SELECT to_regclass(:t)"), {"t": f"public.{table_name}"}).scalar() is not None


def upgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    if not _table_exists(conn, 'cows'):
        return

    unique_constraints = inspector.get_unique_constraints('cows')
    for constraint in unique_constraints:
        columns = constraint.get('column_names') or []
        if columns == ['tag_number']:
            op.drop_constraint(constraint['name'], 'cows', type_='unique')

    indexes = inspector.get_indexes('cows')
    for index in indexes:
        if index.get('unique') and index.get('column_names') == ['tag_number']:
            op.drop_index(index['name'], table_name='cows')

    op.create_unique_constraint('uq_cows_tenant_tag_number', 'cows', ['tenant_id', 'tag_number'])


def downgrade():
    conn = op.get_bind()
    if not _table_exists(conn, 'cows'):
        return

    op.drop_constraint('uq_cows_tenant_tag_number', 'cows', type_='unique')
    op.create_unique_constraint('uq_cows_tag_number', 'cows', ['tag_number'])