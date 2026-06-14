"""Add drive node table.

Revision ID: c2d3e4f5a6b7
Revises: a0b1c2d3e4f5
"""

from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from open_webui.migrations.util import get_existing_tables


revision: str = 'c2d3e4f5a6b7'
down_revision: str | None = 'a0b1c2d3e4f5'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    existing_tables = set(get_existing_tables())

    if 'drive_node' not in existing_tables:
        op.create_table(
            'drive_node',
            sa.Column('id', sa.Text(), nullable=False),
            sa.Column('space', sa.String(length=20), nullable=False),
            sa.Column('owner_id', sa.Text(), nullable=True),
            sa.Column('parent_id', sa.Text(), nullable=True),
            sa.Column('name', sa.Text(), nullable=False),
            sa.Column('node_type', sa.String(length=20), nullable=False),
            sa.Column('mime_type', sa.Text(), nullable=True),
            sa.Column('size', sa.BigInteger(), nullable=True),
            sa.Column('storage_path', sa.Text(), nullable=True),
            sa.Column('source_node_id', sa.Text(), nullable=True),
            sa.Column('created_by', sa.Text(), nullable=False),
            sa.Column('updated_by', sa.Text(), nullable=False),
            sa.Column('created_at', sa.BigInteger(), nullable=False),
            sa.Column('updated_at', sa.BigInteger(), nullable=False),
            sa.ForeignKeyConstraint(['parent_id'], ['drive_node.id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('id'),
        )
        op.create_index(
            'idx_drive_node_space_owner_parent',
            'drive_node',
            ['space', 'owner_id', 'parent_id'],
        )
        op.create_index('idx_drive_node_parent_id', 'drive_node', ['parent_id'])
        op.create_index('idx_drive_node_source_node_id', 'drive_node', ['source_node_id'])


def downgrade() -> None:
    existing_tables = set(get_existing_tables())

    if 'drive_node' in existing_tables:
        op.drop_index('idx_drive_node_source_node_id', table_name='drive_node')
        op.drop_index('idx_drive_node_parent_id', table_name='drive_node')
        op.drop_index('idx_drive_node_space_owner_parent', table_name='drive_node')
        op.drop_table('drive_node')
