"""drop global unique cows tag index

Revision ID: dca1b9eb738e
Revises: d1f840c1924f
Create Date: 2026-07-08 17:38:36.818881

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'dca1b9eb738e'
down_revision = 'd1f840c1924f'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if 'cows' not in inspector.get_table_names():
        return

    indexes = inspector.get_indexes('cows')
    for index in indexes:
        if index.get('name') == 'ix_cows_tag_number' and index.get('unique'):
            op.drop_index('ix_cows_tag_number', table_name='cows')
            break

    refreshed_indexes = sa.inspect(bind).get_indexes('cows')
    if not any(index.get('name') == 'ix_cows_tag_number' for index in refreshed_indexes):
        op.create_index('ix_cows_tag_number', 'cows', ['tag_number'], unique=False)


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if 'cows' not in inspector.get_table_names():
        return

    indexes = inspector.get_indexes('cows')
    for index in indexes:
        if index.get('name') == 'ix_cows_tag_number' and not index.get('unique'):
            op.drop_index('ix_cows_tag_number', table_name='cows')
            break

    refreshed_indexes = sa.inspect(bind).get_indexes('cows')
    if not any(index.get('name') == 'ix_cows_tag_number' for index in refreshed_indexes):
        op.create_index('ix_cows_tag_number', 'cows', ['tag_number'], unique=True)
