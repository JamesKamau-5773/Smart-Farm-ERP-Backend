"""add genetic profile and trait scores

Revision ID: a1b2c3d4e5f6
Revises: f4a2c8d1e7b9
Create Date: 2026-07-17 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = 'a1b2c3d4e5f6'
down_revision = 'f4a2c8d1e7b9'
branch_labels = None
depends_on = None


def upgrade():
    # Lookup table — seeded by a separate data migration or admin tooling.
    op.create_table(
        'genetic_trait_definitions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('display_name', sa.String(length=100), nullable=False),
        sa.Column('category', sa.String(length=50), nullable=False),
        sa.Column('unit', sa.String(length=50), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name', name='uq_genetic_trait_definitions_name'),
    )

    op.create_table(
        'genetic_profiles',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('cow_id', sa.Integer(), nullable=False),
        sa.Column('tenant_id', sa.Integer(), nullable=False),
        sa.Column('source', sa.String(length=50), nullable=False, server_default='MANUAL'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text('NOW()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text('NOW()')),
        sa.ForeignKeyConstraint(['cow_id'], ['cows.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('cow_id', name='uq_genetic_profiles_cow_id'),
    )
    op.create_index('ix_genetic_profiles_cow_id', 'genetic_profiles', ['cow_id'])
    op.create_index('ix_genetic_profiles_tenant_id', 'genetic_profiles', ['tenant_id'])

    op.create_table(
        'genetic_trait_scores',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('profile_id', sa.Integer(), nullable=False),
        sa.Column('trait_definition_id', sa.Integer(), nullable=False),
        sa.Column('value', sa.Numeric(precision=10, scale=4), nullable=False),
        sa.Column('reliability', sa.Integer(), nullable=False, server_default='50'),
        sa.Column('scored_source', sa.String(length=50), nullable=False,
                  server_default='USER_INPUT'),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text('NOW()')),
        sa.CheckConstraint('reliability >= 0 AND reliability <= 100',
                           name='ck_genetic_trait_score_reliability'),
        sa.ForeignKeyConstraint(['profile_id'], ['genetic_profiles.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['trait_definition_id'], ['genetic_trait_definitions.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('profile_id', 'trait_definition_id',
                            name='uq_genetic_trait_score_profile_trait'),
    )
    op.create_index('ix_genetic_trait_scores_profile_id', 'genetic_trait_scores', ['profile_id'])

    # Seed the standard trait definitions.
    op.bulk_insert(
        sa.table(
            'genetic_trait_definitions',
            sa.column('name', sa.String),
            sa.column('display_name', sa.String),
            sa.column('category', sa.String),
            sa.column('unit', sa.String),
        ),
        [
            # Production traits
            {'name': 'milk_volume',    'display_name': 'Milk Volume',    'category': 'Production',    'unit': 'liters/day'},
            {'name': 'fat_percentage', 'display_name': 'Fat %',          'category': 'Production',    'unit': '%'},
            {'name': 'protein_percentage', 'display_name': 'Protein %',  'category': 'Production',    'unit': '%'},
            # Health & Fitness traits
            {'name': 'mastitis_resistance', 'display_name': 'Mastitis Resistance', 'category': 'Health', 'unit': 'score'},
            {'name': 'productive_life',     'display_name': 'Productive Life',     'category': 'Health', 'unit': 'months'},
            {'name': 'somatic_cell_count',  'display_name': 'Somatic Cell Count',  'category': 'Health', 'unit': '1000 cells/ml'},
            # Conformation traits
            {'name': 'udder_attachment', 'display_name': 'Udder Attachment', 'category': 'Conformation', 'unit': 'score'},
            {'name': 'foot_angle',       'display_name': 'Foot Angle',       'category': 'Conformation', 'unit': 'score'},
        ],
    )


def downgrade():
    op.drop_index('ix_genetic_trait_scores_profile_id', table_name='genetic_trait_scores')
    op.drop_table('genetic_trait_scores')
    op.drop_index('ix_genetic_profiles_tenant_id', table_name='genetic_profiles')
    op.drop_index('ix_genetic_profiles_cow_id', table_name='genetic_profiles')
    op.drop_table('genetic_profiles')
    op.drop_table('genetic_trait_definitions')
